import os
import re
import subprocess
from os.path import join as joinpath, isfile

import requests

from job_schedulers import DEFAULT_PARTITIONS, DEFAULT_GPU_PARTITIONS, DEFAULT_GPU_TYPES

BUILDKITE_PATH = os.environ['BUILDKITE_PATH']
BUILDKITE_QUEUE = os.environ['BUILDKITE_QUEUE']

METRICS_ENDPOINT = 'https://agent.buildkite.com/v3/metrics/queue'

# Queues to watch, comma-separated. Defaults to the single queue this cluster
# already runs the REST-mode poller against.
BUILDKITE_QUEUES = [
    q.strip() for q in
    os.environ.get('BUILDKITE_QUEUES', BUILDKITE_QUEUE).split(',')
    if q.strip()
]

# Cap on new agents submitted per queue per poll, so a metrics spike (or a bug
# in this script) can't flood the Slurm queue in one pass.
MAX_AGENTS_PER_QUEUE = int(os.environ.get('MAX_AGENTS_PER_QUEUE', '10'))

SLURM_TIMELIMIT = os.environ.get('SLURM_TIMELIMIT', '01:05:00')
SLURM_QOS = os.environ.get('SLURM_QOS')
# Override the queue-name-derived GPU type for every queue, if set.
SLURM_GPU_TYPE_OVERRIDE = os.environ.get('SLURM_GPU_TYPE')

# Queue name convention for GPU sizing: '<base>_<N>gpu' requests N GPUs on
# partition/type looked up for '<base>' in job_schedulers' maps; a bare queue
# name with no suffix is treated as CPU-only. This lets metrics-mode reuse the
# same per-cluster maps REST-mode already maintains instead of a second config
# surface.
QUEUE_GPU_SUFFIX = re.compile(r'^(?P<base>.+)_(?P<count>\d+)gpu$')


def _agent_token():
    """Resolve the Buildkite cluster agent token: BUILDKITE_AGENT_TOKEN env
    var, or the `token=` line out of the agent config every cluster already
    has for running `buildkite-agent start` (see set_up_guide.md). Unlike
    REST mode's BUILDKITE_API_TOKEN, no *user* API token is ever required."""
    token = os.environ.get('BUILDKITE_AGENT_TOKEN')
    if token:
        return token

    cfg_path = joinpath(BUILDKITE_PATH, 'buildkite-agent.cfg')
    if isfile(cfg_path):
        with open(cfg_path, 'r') as f:
            for line in f:
                match = re.match(r'^\s*token\s*=\s*"?([^"\s]+)"?\s*$', line)
                if match:
                    return match.group(1)

    raise RuntimeError(
        'No agent token found: set BUILDKITE_AGENT_TOKEN or add a token= '
        f'line to {cfg_path}'
    )


def _queue_gpu_spec(queue):
    """Return (base_queue, gpu_count) for a queue name, per the '<base>_<N>gpu'
    convention. gpu_count is 0 for a bare queue name (CPU-only)."""
    match = QUEUE_GPU_SUFFIX.match(queue)
    if match:
        return match.group('base'), int(match.group('count'))
    return queue, 0


def _queue_metrics(logger, token, queue):
    """Fetch {scheduled, idle, busy} for one queue from the Agent Metrics API."""
    resp = requests.get(
        METRICS_ENDPOINT,
        params={'name': queue},
        headers={'Authorization': f'Token {token}'},
    )
    resp.raise_for_status()
    data = resp.json()
    jobs = data.get('jobs', {})
    agents = data.get('agents', {})
    return {
        'scheduled': jobs.get('scheduled', 0),
        'idle': agents.get('idle', 0),
        'busy': agents.get('busy', 0),
    }


def _pending_slurm_agents(queue):
    """Count Slurm jobs for this queue's generic agents that are still PENDING
    (i.e. haven't registered as a Buildkite agent yet, so the Metrics API
    can't see them). Without this, a backed-up Slurm queue reads as `have = 0`
    every poll and gets flooded with duplicate submissions."""
    job_name = f'bk-metrics-{queue}'
    out = subprocess.run(
        ['squeue', '-h', '--name', job_name, '--states=PENDING', '--noheader'],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout.decode('utf-8')
    return sum(1 for line in out.splitlines() if line.strip())


def _submit_generic_agent(logger, queue):
    base_queue, gpu_count = _queue_gpu_spec(queue)

    cmd = [
        'sbatch',
        '--parsable',
        f'--job-name=bk-metrics-{queue}',
        f'--time={SLURM_TIMELIMIT}',
    ]

    if gpu_count > 0:
        gpu_type = SLURM_GPU_TYPE_OVERRIDE or DEFAULT_GPU_TYPES.get(base_queue)
        gres = f'gpu:{gpu_type}:{gpu_count}' if gpu_type else f'gpu:{gpu_count}'
        cmd.append(f'--gres={gres}')
        partition = DEFAULT_GPU_PARTITIONS.get(base_queue)
    else:
        partition = DEFAULT_PARTITIONS.get(base_queue)

    if partition:
        cmd.append(f'--partition={partition}')
    if SLURM_QOS:
        cmd.append(f'--qos={SLURM_QOS}')

    # BUILDKITE_PATH is passed positionally, not inherited from the submitting
    # shell's environment: some Slurm variants don't reliably propagate env
    # vars into the batch script.
    cmd.append(joinpath(BUILDKITE_PATH, 'bin/schedule_agent.sh'))
    cmd.append(queue)
    cmd.append(BUILDKITE_PATH)

    logger.debug(f"Slurm command: {' '.join(cmd)}")
    try:
        result = subprocess.run(
            cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        logger.info(f"Submitted generic agent for queue '{queue}', Slurm job {result.stdout.strip()}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Slurm error submitting generic agent for queue '{queue}': {e.stderr}")


def run(logger):
    token = _agent_token()

    for queue in BUILDKITE_QUEUES:
        try:
            metrics = _queue_metrics(logger, token, queue)
            pending = _pending_slurm_agents(queue)

            need = metrics['scheduled']
            have = metrics['idle'] + metrics['busy'] + pending

            to_submit = max(0, min(need - have, MAX_AGENTS_PER_QUEUE))
            logger.info(
                f"Queue '{queue}': need={need} have={have} "
                f"(idle={metrics['idle']}, busy={metrics['busy']}, pending={pending}), "
                f"submitting {to_submit}"
            )

            for _ in range(to_submit):
                _submit_generic_agent(logger, queue)

        except Exception:
            logger.error(f"Caught exception while polling queue '{queue}'", exc_info=True)
