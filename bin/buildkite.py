import datetime
from datetime import datetime, date, timedelta
import requests
import os
from os.path import join as joinpath

BUILDS_ENDPOINT = 'https://api.buildkite.com/v2/organizations/clima/builds'

BUILDKITE_PATH = os.environ['BUILDKITE_PATH']
BUILDKITE_QUEUE = os.environ['BUILDKITE_QUEUE']

BUILDKITE_API_TOKEN = os.environ.get(
'BUILDKITE_API_TOKEN',
open(joinpath(BUILDKITE_PATH,'.buildkite_token'), 'r').read().rstrip()
)

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
