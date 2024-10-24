import datetime
from datetime import datetime, timedelta
import requests
import os
import re
from os.path import join as joinpath, isfile

BUILDS_ENDPOINT = 'https://api.buildkite.com/v2/organizations/clima/builds'

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

def get_buildkite_job_tags(job):
    agent_query_rules = job.get('agent_query_rules', [])
    tag_dict = {}
    for item in agent_query_rules:
        if '=' in item:
            key, value = item.split('=', 1)  # Split on first '=' only
            tag_dict[key] = value
    
    return tag_dict

# Sanitize a pipeline name to use it in a URL
# Lowers and replaces any groups of non-alphanumeric character with a '-'
def sanitize_pipeline_name(name):
    return re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')

def build_url(pipeline_name, build_num):
    return f"https://buildkite.com/clima/{sanitize_pipeline_name(pipeline_name)}/builds/{build_num}"

# we pick an nhour timedelta for the build window,
# but it just needs to be more than that cron poll interval
def hours_ago_utc(nhours):
    return (datetime.utcnow() - timedelta(hours=nhours)).replace(microsecond=0).isoformat() + 'Z'

# we pick a day ago timedelta for the cancel window,
# to catch problematic overnight runs
def day_ago_utc():
    return (datetime.utcnow() - timedelta(days=1)).replace(microsecond=0).isoformat() + 'Z'

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
