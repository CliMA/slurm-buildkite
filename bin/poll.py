#!/usr/bin/env python3
import datetime
import logging
import os
import re
import requests
import subprocess

from datetime import datetime, date, timedelta
from os.path import join as joinpath, isfile

# debug flag, set this to true to get log output
# of state change transitions but do not actually
# submit the slurm commands on the cluster

# If DEBUG_SLURM_BUILDKITE is set, we are in the Debug mode
DEBUG = "DEBUG_SLURM_BUILDKITE" in os.environ

# Time window to query buildkite jobs
NHOURS = 96

# setup root logger
logger = logging.Logger('poll')
handler = logging.StreamHandler()
handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(levelname)s: %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)
if DEBUG:
    logger.info("Debug mode!")

BUILDS_ENDPOINT = 'https://api.buildkite.com/v2/organizations/clima/builds'

# we pick an nhour timedelta for the build window,
# but it just needs to be more than that cron poll interval
def hours_ago_utc(nhours):
    return (datetime.utcnow() - timedelta(hours=nhours)).replace(microsecond=0).isoformat() + 'Z'

# we pick a day ago timedelta for the cancel window,
# to catch problematic overnight runs
def day_ago_utc():
    return (datetime.utcnow() - timedelta(days=1)).replace(microsecond=0).isoformat() + 'Z'

# Map from buildkite queue to slurm partition
DEFAULT_PARTITIONS = {"clima": "batch", "new-central": "expansion"}
DEFAULT_GPU_PARTITIONS = {"clima": "batch", "new-central": "gpu"}

# Map from buildkite queue to slurm reservation
DEFAULT_RESERVATIONS = {"new-central": "clima"}

# Retrieve all 'scheduled', 'running', 'failing' builds in the last nhours
def all_started_builds(nhours): 
    since = hours_ago_utc(nhours=nhours)
    npage, builds = 1, []
    while True:
        req = requests.get(
            BUILDS_ENDPOINT,
            params = {
                'page' : npage,
                'per_page' : 100,
                'state[]' : ['scheduled', 'running', 'failing'],
                'created_from' : since
            },
            headers = {
                'Authorization': 'Bearer ' + BUILDKITE_API_TOKEN
            }
        )

        resp = req.json()
        if not len(resp):
            break
        builds.extend(resp)
        npage += 1
    return builds


def all_canceled_builds():
    since = day_ago_utc()
    npage, builds = 1, []
    while True:
        resp = requests.get(
            BUILDS_ENDPOINT,
            params = {
                'page' : npage,
                'per_page' : 100,
                'state[]' : ['canceling', 'canceled'],
                'finished_from' : since
            },
            headers = {
                'Authorization': f'Bearer {BUILDKITE_API_TOKEN}'
            }
        ).json()
        if not len(resp):
            break
        builds.extend(resp)
        npage += 1
    return builds

# Try to guess if this given argument implies that a GPU was requested
def gpu_is_requested(slurm_args, agent_query_rules):
    # Just find the word "gpu" in the tag or in its value. It might be a very
    # wide filter...
    gpu_in_slurm_args = any("gpu" in s for s in slurm_args)
    gpu_in_slurm_values = any("gpu" in agent_query_rules[key] for key in slurm_args)
    return gpu_in_slurm_args or gpu_in_slurm_values

# Sanitize a pipeline name to use it in a URL
# Lowers and replaces any groups of non-alphanumeric character with a '-'
def sanitize_pipeline_name(name):
    return re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')

try:

    BUILDKITE_PATH = os.environ['BUILDKITE_PATH']
    BUILDKITE_QUEUE = os.environ['BUILDKITE_QUEUE']

    BUILDKITE_API_TOKEN = os.environ.get(
        'BUILDKITE_API_TOKEN',
        open(joinpath(BUILDKITE_PATH,'.buildkite_token'), 'r').read().rstrip()
    )

    exclude_nodes_path = joinpath(BUILDKITE_PATH, '.exclude_nodes')
    # Check if the file exists and read its content, otherwise fallback to an empty string
    if isfile(exclude_nodes_path):
        exclude_nodes_from_file = open(exclude_nodes_path, 'r').read().rstrip()
    else:
        exclude_nodes_from_file = ''

    # Get the value from environment variable, or fallback to the file content or an empty string
    BUILDKITE_EXCLUDE_NODES = os.environ.get('BUILDKITE_EXCLUDE_NODES', exclude_nodes_from_file)


    # check the currently running jobs for their buildkite ids and slurmjob ids
    # %k prints the comment, which contains the buildkite link
    squeue = subprocess.run(['squeue',
                             '--name=buildkite',
                             '--noheader',
                             '--format=%k,%A'],
                            stdout=subprocess.PIPE)

    currentjobs = dict()
    for line in squeue.stdout.decode('utf-8').splitlines():
        buildkite_url, slurm_job_id = line.split(',', 1)
        currentjobs.setdefault(buildkite_url, []).append(slurm_job_id)

    logger.debug(f"Current jobs: {list(currentjobs.keys())}")
 
    for url in currentjobs.keys():
        if len(currentjobs[url]) > 1:
            logger.warning(f"{url} has multiple slurmjobs: {currentjobs[url]})")

    logger.info(f"Current slurm jobs (submitted or started): {len(currentjobs)}")

    # poll the buildkite API to check if there are any scheduled/running builds
    builds = all_started_builds(NHOURS)

    # Accumulate jobs to be canceled in one batch 
    cancel_slurm_jobids = []

    # loop over all scheduled and running builds for all pipelines in the buildkite org
    for build in builds:

        # get the build id, number and pipeline
        #  redirect job logs per unique build id
        buildid = build['id']
        buildnum = build['number']
        pipeline = build['pipeline']
        pipeline_name = pipeline['name']

        # for all jobs in this build
        for job in build['jobs']:

            # jobid, jobtype are attributes in every job object
            jobid, jobtype = job['id'], job['type']

            # don't schedule non-script jobs on slurm
            if jobtype != 'script':
                continue

            # this job is a script job, check if it has a scheduled state
            # and not submitted as slurm job
            # valid states: running, scheduled, passed, failed, blocked,
            #               canceled, canceling, skipped, not_run, finished
            # https://buildkite.com/docs/pipelines/defining-steps#build-states
            jobstate = job['state']
            buildkite_url = job['web_url']

            # Cancel jobs marked by buildkite as 'canceled'
            if jobstate == 'canceled':
                if buildkite_url in currentjobs:
                    cancel_slurm_jobids.extend(currentjobs[buildkite_url])
                else:
                    logger.warning(f"Canceled job {buildkite_url} not found in current jobs.")
                continue

            # jobstate is not pending, or a scheduled job (but not running yet)
            # is already submitted to slurm
            if jobstate != 'scheduled' or buildkite_url in currentjobs:
                continue

            # Directory containing slurm logs for given build
            slurmlog_dir = joinpath(
                BUILDKITE_PATH,
                'logs',
                f'{date.today()}',
                f'build_{buildid}',
            )
            # Create the directory prefix if it does not exist
            if not os.path.isdir(slurmlog_dir):
                build_link = f"https://buildkite.com/clima/{sanitize_pipeline_name(pipeline_name)}/builds/{buildnum}"
                logger.info(f"New build: {pipeline_name} - {build_link}")
                if not DEBUG:
                    os.mkdir(slurmlog_dir)
            
            # The comment section is used to scan jobids and ensure we are not
            # submitting multiple copies of the same job. This happens at the
            # beginning of the try-catch, in the squeue command.
            cmd = [
                'sbatch',
                '--parsable',
                '--comment=' + buildkite_url,
                '--output=' + joinpath(slurmlog_dir, 'slurm-%j.log')
            ]
            agent_query_rules = job.get('agent_query_rules', [])
            agent_query_rules = {item.split('=')[0]: item.split('=')[1] for item in agent_query_rules}

            agent_queue = agent_query_rules.get('queue', None)

            # Only log jobs on current queue unless debugging or missing queue
            if agent_queue is None:
                logger.error(f"New job missing queue. Pipeline: {pipeline_name}, {buildkite_url}")
                continue
            elif agent_queue == BUILDKITE_QUEUE:
                logger.info(f"New job on `{agent_queue}`. Pipeline: {pipeline_name}, {buildkite_url}")
            
            if agent_queue != BUILDKITE_QUEUE:
                continue

            # Pass arguments starting with `slurm_` through to sbatch.
            # To pass flags, set them to true, e.g. slurm_exclusive: true
            slurm_keys = list(filter(lambda x: x.startswith('slurm_'), agent_query_rules.keys()))
            for key in slurm_keys:
                value = agent_query_rules[key]
                arg = key.split('slurm_', 1)[1].replace('_', '-')
                # If the value is 'true', we know this is a flag instead of an argument
                if value.lower() == 'true':
                    cmd.append(f"--{arg}")
                else:
                    cmd.append(f"--{arg}={value}")

            # Set partition depending on if a GPU has been requested
            # Fallback to 'default' if there is no default partition
            if gpu_is_requested(slurm_keys, agent_query_rules):
                default_partition = DEFAULT_GPU_PARTITIONS[agent_queue]
            else:
                default_partition = DEFAULT_PARTITIONS[agent_queue]

            agent_partition = agent_query_rules.get('partition', default_partition)
            cmd.append(f"--partition={agent_partition}")

            # Check that there is no user-given reservation and that there
            # is a valid default reservation
            default_reservation = DEFAULT_RESERVATIONS.get(agent_queue, None)
            if "slurm_reservation" not in slurm_keys and default_reservation:
                cmd.append(f"--reservation={default_reservation}")

            use_exclude = agent_query_rules.get('exclude', 'true')
            if use_exclude == 'true' and BUILDKITE_EXCLUDE_NODES:
                cmd.append(f"--exclude={BUILDKITE_EXCLUDE_NODES}")

            cmd.append(joinpath(BUILDKITE_PATH, 'bin/slurmjob.sh'))
            cmd.append(jobid)

            agent_modules = agent_query_rules.get('modules', "")
            if agent_modules != "":
                cmd.append(agent_modules)

            if not DEBUG:
                ret = subprocess.run(cmd,
                                     stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE,
                                     universal_newlines=True)
                if ret.returncode != 0:
                    # TODO: Run a minimal failing slurm job to return the error to buildkite
                    logger.error(
                        f"Slurm error during job submission, retcode={ret.returncode}: "
                        f"`{' '.join(cmd)}`\n{ret.stderr}"
                    )
                    continue

                slurmjob_id = int(ret.stdout)
                log_path = joinpath(slurmlog_dir, f'slurm-{slurmjob_id}.log')
                logger.info(f"Slurm job submitted, ID: {slurmjob_id}, log: {log_path}")
            else:
                logger.info(f"Buildkite link: {buildkite_url}")
                logger.info(f"Slurm command: {' '.join(cmd)}")

    # Cancel jobs in canceled builds
    canceled_builds = all_canceled_builds()

    for build in canceled_builds:
        for job in build['jobs']:
            if job['type'] == 'script':
                buildkite_url = job['web_url']
                if buildkite_url in currentjobs:
                    cancel_slurm_jobids.extend(currentjobs[buildkite_url])

    # Cancel individually marked slurm jobs in one call
    if cancel_slurm_jobids:
        logger.info(f"Canceling {len(cancel_slurm_jobids)} slurm  jobs")

        cmd = ['scancel', '--name=buildkite']
        cmd.extend(cancel_slurm_jobids)

        if not DEBUG:
            ret = subprocess.run(cmd,
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE,
                                 universal_newlines=True)
            if ret.returncode != 0:
                logger.error(
                    f"Slurm error when canceling jobs, retcode={ret.returncode}: "
                    f"`{' '.join(cmd)}`\n{ret.stderr}"
                )

except Exception:
    logger.error("Caught exception during poll",  exc_info=True)
