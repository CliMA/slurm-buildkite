#!/usr/bin/env python3
import datetime
import logging
import os
import requests
import subprocess

from datetime import datetime, date, timedelta
from os.path import join as joinpath

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

# What SLURM partition to use by default depending on the queue
DEFAULT_PARTITIONS = {"default": "default", "new-central": "any", "new-central": "expansion"}
DEFAULT_GPU_PARTITIONS = {"default": "default", "new-central": "any", "new-central": "gpu"}

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
def gpu_is_requested(slurm_arg, val):
    # Just find the word "gpu" in the tag or in its value. It might be a very
    # wide filter...
    return "gpu" in slurm_arg or "gpu" in val

try:
    # optional env overloads
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
        'central'
    )

    BUILDKITE_EXCLUDE_NODES = os.environ.get(
        'BUILDKITE_EXCLUDE_NODES',
        open(joinpath(BUILDKITE_PATH,'.exclude_nodes'), 'r').read().rstrip()
    )

    # check the currently running jobs for their buildkite ids and slurmjob ids
    squeue = subprocess.run(['squeue',
                             '--name=buildkite',
                             '--noheader',
                             '--format=%k,%A'],
                            stdout=subprocess.PIPE)

    currentjobs = dict()
    for line in squeue.stdout.decode('utf-8').splitlines():
        buildkite_job_id, slurm_job_id = line.split(',', 1)
        currentjobs[buildkite_job_id] = slurm_job_id

    logger.info('jobs in slurm queue: {0}'.format(len(currentjobs)))


    # poll the buildkite API to check if there are any scheduled/running builds
    builds = all_started_builds()

    # loop over all scheduled and running builds for all pipelines in the organiation

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

            logger.info('  new job: pipeline: {0}, number: {1}, build id: {2}, job id: {3}' \
                        .format(pipeline['name'], buildnum, buildid, jobid))

            # passthough the job id as a comment to the slurm job
            # which can be queried with %k
            cmd = [
                'sbatch',
                '--parsable',
                '--comment=' + jobid,
                '--output=' + joinpath(slurmlog_prefix, 'slurm-%j.log')
            ]


            # parse agent query rule tags
            agent_query_rules = job.get('agent_query_rules', [])
            agent_config = 'default'
            agent_queue  = 'default'
            agent_partition = DEFAULT_PARTITIONS[agent_queue]
            agent_modules = ""
            use_exclude = True
            partition_has_changed = False

            for tag in agent_query_rules:
                # e.g. tag = 'slurm_ntasks=3'
                key, val = tag.split('=', 1)

                if key == 'queue':
                    agent_queue = val
                    # We read the queue, we need to update the default
                    # partition, unless the partition was already read (the
                    # user-provided agent tag has to take the precedence)
                    if not partition_has_changed:
                        agent_partition = DEFAULT_PARTITIONS.get(agent_queue, None)
                    continue

                if key == 'config':
                    agent_config = val
                    continue

                if key == 'partition':
                    agent_partition = val
                    # We flag that we changed the partition, so if we read the
                    # queue argument, we know we don't have to reset the
                    # partition
                    partition_has_changed = True
                    continue

                if key == "modules":
                    agent_modules = val
                    continue

                # passthrough all agent slurm prefixed query rules to the slurm job
                if key.startswith('slurm_'):
                    slurm_arg = key.split('slurm_', 1)[1].replace('_', '-')

                    # If we are requesting a GPU and we haven't specified a
                    # partition, let's switch the partition to the default GPU
                    # partition
                    if gpu_is_requested(slurm_arg, val) and not partition_has_changed:
                        agent_partition = DEFAULT_GPU_PARTITIONS.get(agent_queue, None)

                    if slurm_arg == "exclude":
                        use_exclude = False

                    if val:
                        cmd.append('--{0}={1}'.format(slurm_arg, val))
                    else:
                        # flag with no value
                        cmd.append('--{0}'.format(slurm_arg))

            # exclude node hosts that may be problematic (comma sep string)
            if use_exclude and BUILDKITE_EXCLUDE_NODES:
                cmd.append("--exclude=" + BUILDKITE_EXCLUDE_NODES)

            if not agent_queue in (BUILDKITE_QUEUE, 'default'):
                continue

            cmd.append("--partition={}".format(agent_partition))

            cmd.append(joinpath(BUILDKITE_PATH, 'bin/slurmjob.sh'))
            cmd.append(agent_config)
            cmd.append(jobid)
            if agent_modules:
                cmd.append(agent_modules)

            slurmjob_id = 0
            if not DEBUG:
                logger.info("new slurm jobid={0}: `{1}` (queue: {2}, hostname: {3})".format(slurmjob_id, " ".join(cmd), agent_queue, os.uname()[1]))
                ret = subprocess.run(cmd,
                                     stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE,
                                     universal_newlines=True)
                if ret.returncode != 0:
                    logger.error(
                        "slurm error retcode={0}: `{1}`\n{2}" \
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
                    "slurm error retcode={0}: `{1}`\n{2}").format(ret.returncode,
                                                                  " ".join(cmd),
                                                                  ret.stderr)

except Exception:
    logger.error("Caught exception during poll",  exc_info=True)
