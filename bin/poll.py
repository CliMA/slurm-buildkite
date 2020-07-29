#!/usr/bin/env python3
import requests
import subprocess
from os.path import join as joinpath


BUILDKITE_PATH = "/groups/esm/buildkite"
TOKEN = open(joinpath(BUILDKITE_PATH,'.api_token'), 'r').read().rstrip()

# poll the buildkite API to check if there are any scheduled builds
builds = requests.get('https://api.buildkite.com/v2/organizations/clima/builds?state=scheduled',
                 headers={'Authorization': 'Bearer '+TOKEN}).json()

# check the currently running jobs for their buildkite ids
squeue = subprocess.run(['squeue',
                         '--name=buildkite',
                         '--noheader',
                         '--format=%k'],
                        stdout=subprocess.PIPE)
currentjobs = set(squeue.stdout.decode('utf-8').splitlines())

for build in builds:
    for job in build["jobs"]:
        id = job["id"]
        if id in currentjobs:
            continue

        # build sbatch command
        cmd = ['sbatch',
               '--comment='+id,
               '--output='+joinpath(BUILDKITE_PATH, 'logs/slurm-%j.out')
               ]
        
        for tag in job["agent_query_rules"]:
            # ntasks=3
            key,val = tag.split('=',1)
            if key in ["ntasks","gres"]:
                cmd.append('--'+tag)

        cmd.append(joinpath(BUILDKITE_PATH, 'bin/slurmjob.sh'))
        cmd.append(id)
                
        subprocess.run(cmd)

