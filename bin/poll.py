#!/usr/bin/env python3
import datetime
import logging
import os
import requests
import subprocess

from datetime import datetime, date, timedelta
from os.path import join as joinpath, isfile

# debug flag, set this to true to get log output
# of state change transitions but do not actually
# submit the slurm commands on the cluster

# If DEBUG_SLURM_BUILDKITE is set, we are in the Debug mode
DEBUG = "DEBUG_SLURM_BUILDKITE" in os.environ

# setup root logger
logger = logging.Logger('poll')
handler = logging.StreamHandler()
handler.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
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
DEFAULT_PARTITIONS = {"clima": "default", "new-central": "expansion"}
DEFAULT_GPU_PARTITIONS = {"clima": "default", "new-central": "gpu"}

def all_started_builds():
    since = hours_ago_utc(nhours=48)
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
                'Authorization': 'Bearer ' + BUILDKITE_API_TOKEN
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

try:
    # TODO: BUILDKITE_PATH and BUILDKITE_QUEUE should not have defaults
    BUILDKITE_PATH = os.environ.get(
        'BUILDKITE_PATH',
        '/groups/esm/slurm-buildkite'
    )

    BUILDKITE_API_TOKEN = os.environ.get(
        'BUILDKITE_API_TOKEN',
        open(joinpath(BUILDKITE_PATH,'.buildkite_token'), 'r').read().rstrip()
    )

    BUILDKITE_QUEUE = os.environ.get(
        'BUILDKITE_QUEUE',
        'new-central'
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
    # %k prints the comment, which is the form: buildid____link
    squeue = subprocess.run(['squeue',
                             '--name=buildkite',
                             '--noheader',
                             '--format=%k,%A'],
                            stdout=subprocess.PIPE)

    currentjobs = dict()
    for line in squeue.stdout.decode('utf-8').splitlines():
        buildkite_job_id_and_link, slurm_job_id = line.split(',', 1)
        buildkite_job_id = buildkite_job_id_and_link.split("___")[0]
        currentjobs[buildkite_job_id] = slurm_job_id

    logger.info('jobs in slurm queue: {0}'.format(len(currentjobs)))


    # poll the buildkite API to check if there are any scheduled/running builds
    builds = all_started_builds()

    # loop over all scheduled and running builds for all pipelines in the organization

    # cancel any previous build jobs, collect these first during job submission for any running builds
    # we further collect all canceled build jobs at the end and issue one scancel call
    cancel_slurm_jobids = []

    for build in builds:

        # get the build id, number and pipeline
        #  redirect job logs per unique build id
        buildid = build['id']
        buildnum = build['number']
        pipeline = build['pipeline']

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

            # if an individual job during an scheduled or running build is
            # marked as canceled, add it to the list of jobids to cancel
            if jobstate == 'canceled' and jobid in currentjobs:
                cancel_slurm_jobids.append(currentjobs[jobid])
                continue

            # jobstate is not pending, or a scheduled job (but not running yet)
            # is already submitted to slurm
            if jobstate != 'scheduled' or jobid in currentjobs:
                continue

            # build sbatch command, collect job logs per build id
            slurmlog_prefix = joinpath(
                BUILDKITE_PATH,
                'logs',
                '{0}'.format(date.today()),
                'build_{0}'.format(buildid),
            )

            # slurm does not create a missing path prefix
            # to create the directory prefix if it does not exist
            if not os.path.isdir(slurmlog_prefix):
                logger.info('new build: pipeline: {0}, number: {1}, build id: {2}' \
                            .format(pipeline['name'], buildnum, buildid))
                if not DEBUG:
                    os.mkdir(slurmlog_prefix)

            buildkite_link = "https://buildkite.com/clima/{}/builds/{}#{}".format(pipeline['name'].lower(), buildnum, buildid)

            logger.info('  new job: pipeline: {0}, number: {1}, build id: {2}, job id: {3}' \
                        .format(pipeline['name'], buildnum, buildid, jobid))

            # The comment section is used to scan jobids and ensure we are not
            # submitting multiple copies of the same job. This happens at the
            # beginning of the try-catch, in the squeue command.

            cmd = [
                'sbatch',
                '--parsable',
                '--comment=' + jobid + "___" + buildkite_link,
                '--output=' + joinpath(slurmlog_prefix, 'slurm-%j.log')
            ]

            # parse agent query rule tags
            agent_query_rules = job.get('agent_query_rules', [])
            agent_query_rules = {item.split('=')[0]: item.split('=')[1] for item in agent_query_rules}

            agent_queue = agent_query_rules['queue']
            if agent_queue != BUILDKITE_QUEUE:
                continue

            # Pass arguments starting with `slurm_` through to sbatch.
            # To pass flags, set them to true, e.g. slurm_exclusive: true
            slurm_keys = list(filter(lambda x: x.startswith('slurm_'), agent_query_rules.keys()))
            for key in slurm_keys:
                value = agent_query_rules[key]
                arg = key.split('slurm_', 1)[1].replace('_', '-')
                # If the value is 'true', we know this is a flag instead of an argument
                if value == 'true':
                    cmd.append('--{0}'.format(slurm_arg))
                else:
                    cmd.append('--{0}={1}'.format(arg, value))

            # Set partition depending on if a GPU has been requested
            # Fallback to 'default' if there is no default partition
            if gpu_is_requested(slurm_keys, agent_query_rules):
                default_partition = DEFAULT_GPU_PARTITIONS.get(agent_queue, 'default')
            else:
                default_partition = DEFAULT_PARTITIONS.get(agent_queue, 'default')

            agent_partition = agent_query_rules.get('partition', default_partition)
            cmd.append("--partition={}".format(agent_partition))

            use_exclude = agent_query_rules.get('exclude', 'true')
            if use_exclude == 'true' and BUILDKITE_EXCLUDE_NODES:
                cmd.append("--exclude=" + BUILDKITE_EXCLUDE_NODES)

            cmd.append(joinpath(BUILDKITE_PATH, 'bin/slurmjob.sh'))

            # TODO: What is the 'config'?
            agent_config = agent_query_rules.get('config', 'default')
            cmd.append(agent_config)
            cmd.append(jobid)

            agent_modules = agent_query_rules.get('modules', "")
            if agent_modules != "":
                cmd.append(agent_modules)

            # TODO: Why is this set to 0?
            slurmjob_id = 0
            if not DEBUG:
                logger.info("new slurm jobid={0}: `{1}` (queue: {2}, hostname: {3})".format(slurmjob_id, " ".join(cmd), agent_queue, os.uname()[1]))
                ret = subprocess.run(cmd,
                                     stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE,
                                     universal_newlines=True)
                if ret.returncode != 0:
                    logger.error(
                        "slurm error during job submission, retcode={0}: `{1}`\n{2}" \
                        .format(ret.returncode, " ".join(cmd), ret.stderr))
                    continue
                slurmjob_id = int(ret.stdout)

    # Run canceled job builds at the end
    canceled_builds = all_canceled_builds()

    for build in canceled_builds:
        for job in build['jobs']:
            jobid = job['id']
            if jobid in currentjobs:
                cancel_slurm_jobids.append(currentjobs[jobid])

    # if we have scheduled / running slurm jobs to cancel, cancel them in one call
    if len(cancel_slurm_jobids):
        logger.info('canceling {0} jobs in slurm queue'.format(len(cancel_slurm_jobids)))

        cmd = ['scancel', '--name=buildkite']
        cmd.extend(cancel_slurm_jobids)

        logger.info("new slurm job: `{0}`".format(" ".join(cmd)))
        if not DEBUG:
            ret = subprocess.run(cmd,
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE,
                                 universal_newlines=True)
            if ret.returncode != 0:
                logger.error(
                    "slurm error when cancelling jobs, retcode={0}: `{1}`\n{2}").format(ret.returncode,
                                                                  " ".join(cmd),
                                                                  ret.stderr)

except Exception:
    logger.error("Caught exception during poll",  exc_info=True)
