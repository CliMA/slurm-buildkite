#!/usr/bin/env python3
import datetime
import logging
import os
import requests
import subprocess
from os.path import join as joinpath

# setup root logger
logger = logging.Logger('poll')
handler = logging.StreamHandler()
handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

try:
    # optional env overloads
    BUILDKITE_PATH = os.environ.get(
        'BUILDKITE_PATH', 
        '/groups/esm/buildkite'
    )

    API_TOKEN = os.environ.get(
        'BUILDKITE_API_TOKEN',
        open(joinpath(BUILDKITE_PATH,'.api_token'), 'r').read().rstrip()
    )

    # poll the buildkite API to check if there are any scheduled/running builds
    builds = requests.get(
        'https://api.buildkite.com/v2/organizations/clima/builds?state[]=scheduled&state[]=running',
        headers={'Authorization': 'Bearer ' + API_TOKEN}
    ).json()

    # check the currently running jobs for their buildkite ids
    squeue = subprocess.run(['squeue',
                             '--name=buildkite',
                             '--noheader',
                             '--format=%k'],
                            stdout=subprocess.PIPE)

    currentjobs = set(squeue.stdout.decode('utf-8').splitlines())
    
    logger.info('jobs in slurm queue: {0}'.format(len(currentjobs)))

    # loop over all scheduled and running builds for all pipelines in the organiation
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

            # jobstate is not pending, or a scheduled job (but not running yet)
            # is already submitted to slurm
            if jobstate != 'scheduled' or jobid in currentjobs:
                continue


            # build sbatch command, collect job logs per build id
            slurmlog_prefix = joinpath(
                BUILDKITE_PATH,
                'logs',
                '{0}'.format(datetime.date.today()),
                'build_{0}'.format(buildid),
            )

            # slurm does not create a missing path prefix
            # to create the directory prefix if it does not exist
            if not os.path.isdir(slurmlog_prefix):
                logger.info('new build: pipeline: {0}, number: {1}, build id: {2}' \
                            .format(pipeline['name'], buildnum, buildid))
                os.mkdir(slurmlog_prefix)

            logger.info('  new job: pipeline: {0}, number: {1}, build id: {2}, job id: {3}' \
                        .format(pipeline['name'], buildnum, buildid, jobid))

            # passthough the job id as a comment to the slurm job
            # which can be queried with %k
            cmd = [
                'sbatch',
                '--comment=' + jobid,
                '--output=' + joinpath(slurmlog_prefix, 'slurm-%j.log')
            ]

            # allow passthrough info in agent query desc in pipeline.yml
            if 'agent_query_rules' in job:
                for tag in job['agent_query_rules']:
                    # e.g. tag = "slurm_ntasks=3"
                    key, val = tag.split('=', 1)
                    if not key.startswith('slurm_'):
                        continue
                    # passthrough all agent slurm prefixed query rules to the slurm job
                    slurm_arg = key.split('slurm_', 1)[1]
                    cmd.append('--{0}={1}'.format(slurm_arg, val))

            cmd.append(joinpath(BUILDKITE_PATH, 'bin/slurmjob.sh'))
            cmd.append(jobid)
            
            logger.info("new slurm job: `{0}`".format(" ".join(cmd)))
            subprocess.run(cmd)

except Exception:
    logger.error("Caught exception during poll",  exc_info=True)
