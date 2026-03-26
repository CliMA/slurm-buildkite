import subprocess
import dbm
import json
import os
from os.path import join as joinpath
import re
import shutil
import requests
from buildkite import get_buildkite_job_tags, BUILDKITE_EXCLUDE_NODES
from buildkite import BUILDKITE_PATH, BUILDKITE_QUEUE

DEFAULT_SCHEDULER = os.environ.get('JOB_SYSTEM', 'slurm')
DEFAULT_TIMELIMIT = '1:05:00'

# Map from buildkite queue to slurm partition or PBS queue
DEFAULT_PARTITIONS = {"gcp": "a3,a3mega", "derecho": "preempt@desched1", "test": "batch", "clima": "batch", "central": "expansion"}
DEFAULT_GPU_PARTITIONS = {"gcp": "a3,a3mega", "derecho": "preempt@desched1", "test": "batch", "clima": "batch", "central": "gpu"}

# Map from buildkite queue to HPC reservation
DEFAULT_RESERVATIONS = { "central": "clima_cpu", "derecho": "UCIT0011"}
DEFAULT_GPU_RESERVATIONS = {"central": "clima", "derecho": "UCIT0011"}
# list of clusters with no reservations
NO_RESERVATION_QUEUES = {"clima", "gcp"}
# Map from buildkite queue to PBS server
DEFAULT_PBS_SERVERS = {"derecho": "desched1"}

# Default GPU type per queue, used to set --gres=gpu:type:N
# GPU type can be overridden by explicitly setting slurm_gres
# Queues not listed here will not have a default GPU type applied
DEFAULT_GPU_TYPES = {"central": "p100"}

# Search for the word "gpu" in the given dict
def gpu_is_requested(scheduler_tags):
    found = any("gpu" in key or "gpu" in value for key, value in scheduler_tags.items())
    return found

# Determine the number of GPUs requested from slurm_keys
def get_gpu_count(slurm_keys):
    """
    Extract GPU count from slurm_keys. Checks in order:
    1. slurm_gpus (total GPUs)
    2. slurm_gpus_per_task * slurm_ntasks
    3. slurm_gpus_per_node * slurm_nodes
    6. Default to 1 if no GPU count is found
    """
    # Check for explicit total GPU count
    if 'slurm_gpus' in slurm_keys:
        return int(slurm_keys['slurm_gpus'])

    # Check for gpus_per_task with ntasks
    if 'slurm_gpus_per_task' in slurm_keys:
        gpus_per_task = int(slurm_keys['slurm_gpus_per_task'])
        ntasks = int(slurm_keys.get('slurm_ntasks', 1))
        return gpus_per_task * ntasks

    # Check for gpus_per_node with nodes
    if 'slurm_gpus_per_node' in slurm_keys:
        gpus_per_node = int(slurm_keys['slurm_gpus_per_node'])
        nodes = int(slurm_keys.get('slurm_nodes', 1))
        return gpus_per_node * nodes

    # Default to 1 (only called when GPU is requested, so we need at least 1)
    return 1

class JobScheduler:
    def submit_job(self, logger, build_log_dir, job):
        raise NotImplementedError("Subclass must implement submit_job")

    def cancel_jobs(self, logger, job_ids):
        raise NotImplementedError("Subclass must implement cancel_jobs")

    def current_jobs(self, logger):
        raise NotImplementedError("Subclass must implement current_jobs")

class SlurmJobScheduler(JobScheduler):
    def submit_job(self, logger, build_log_dir, job):
        job_id = job['id']
        buildkite_url = job['web_url']
        tags = get_buildkite_job_tags(job)
        queue = tags['queue']
        cmd = [
            'sbatch',
            '--parsable',
            "--job-name=buildkite",
            f'--comment={buildkite_url}',
            f"--output={joinpath(build_log_dir, 'slurm-%j.log')}",
        ]
        slurm_keys = {k: v for k, v in tags.items() if k.startswith('slurm_')}

        # No reservation, add default if job has < 3 GPUs. Larger jobs can 
        if 'slurm_reservation' not in slurm_keys and queue not in NO_RESERVATION_QUEUES:
            if gpu_is_requested(slurm_keys) and get_gpu_count(slurm_keys) < 3:
                slurm_keys['slurm_reservation'] = DEFAULT_GPU_RESERVATIONS[queue]
            elif not gpu_is_requested(slurm_keys):
                slurm_keys['slurm_reservation'] = DEFAULT_RESERVATIONS[queue]
        # Key exists and reservation == false, remove reservation
        elif slurm_keys.get("slurm_reservation", "").lower() == "false":
            del slurm_keys['slurm_reservation']

        # If the queue has a default GPU type, set --gres=gpu:type:N
        # Only add if user hasn't explicitly set gres
        default_gpu_type = DEFAULT_GPU_TYPES.get(queue)
        if gpu_is_requested(slurm_keys) and default_gpu_type and 'slurm_gres' not in slurm_keys:
            gpu_count = get_gpu_count(slurm_keys)
            slurm_keys['slurm_gres'] = f"gpu:{default_gpu_type}:{gpu_count}"
            # Remove slurm_gpus to avoid conflict with --gres (--gpus and --gres conflict)
            # Keep slurm_gpus_per_task and slurm_gpus_per_node as they may be needed
            # for proper per-task/per-node allocation
            slurm_keys.pop('slurm_gpus', None)
            slurm_keys.pop('slurm_gpus_per_task', None)
            slurm_keys.pop('slurm_gpus_per_node', None)

        for key, value in slurm_keys.items():
            cmd.append(self.format_resource(key, value))

        # Set partition depending on if a GPU has been requested
        # Fallback to 'default' if there is no default partition
        if gpu_is_requested(slurm_keys):
            default_partition = DEFAULT_GPU_PARTITIONS[queue]
        else:
            default_partition = DEFAULT_PARTITIONS[queue]

        agent_partition = tags.get('partition', default_partition)
        cmd.append(f"--partition={agent_partition}")

        use_exclude = tags.get('exclude', 'true')
        if use_exclude == 'true' and BUILDKITE_EXCLUDE_NODES:
            cmd.append(f"--exclude={BUILDKITE_EXCLUDE_NODES}")

        if "slurm_time" not in slurm_keys:
            cmd.append(f"--time={DEFAULT_TIMELIMIT}")

        cmd.append(joinpath(BUILDKITE_PATH, 'bin/schedule_job.sh'))
        cmd.append(job_id)

        modules = tags.get('modules', "")
        if modules != "":
            cmd.append(modules)

        logger.debug(f"Slurm command: {' '.join(cmd)}")
        try:
            result = subprocess.run(
                cmd,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True
            )
            slurm_job_id = int(result.stdout)
            log_path = joinpath(build_log_dir, f'slurm-{slurm_job_id}.log')
            logger.info(f"Slurm job submitted, ID: {slurm_job_id}, log: {log_path}")

        except subprocess.CalledProcessError as e:
            # TODO: Run a minimal failing slurm job to return the error to buildkite
            logger.error(
                f"Slurm error during job submission, retcode={e.returncode}:\n{e.stderr}"
            )

            error_cmd = [
                'sbatch',
                '--parsable',
                "--job-name=bk_error",
                "--time=00:01:00",
                "--ntasks=1",
                f'--comment={buildkite_url}',
                f"--output={joinpath(build_log_dir, 'slurm-%j.log')}",
            ]
            
            default_reservation = DEFAULT_RESERVATIONS.get(queue, None)
            if default_reservation:
                error_cmd.append(f"--reservation={default_reservation}")
            error_cmd.append(joinpath(BUILDKITE_PATH, 'bin/schedule_job.sh'))
            error_cmd.append(job_id)
            error_cmd.append("")
            error_cmd.append(e.stderr)
            try:
                subprocess.run(
                    error_cmd,
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    universal_newlines=True
                )
            except:
                logger.error("Failed to submit error job to Slurm")

    def cancel_jobs(self, logger, job_ids):
        cmd = ['scancel', '--name=buildkite']
        # Flatten list of lists
        cmd.extend([x for sublist in job_ids for x in sublist])
        try:
            logger.info(f"Canceling {len(job_ids)} Slurm jobs")
            logger.debug(cmd)
            subprocess.run(
                cmd,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"Error when canceling Slurm jobs: {' '.join(e.cmd)}")
            logger.error(f"Return code: {e.returncode}")
            logger.error(f"stdout: {e.stdout}")
            logger.error(f"stderr: {e.stderr}")

    def current_jobs(self, logger):
        squeue = subprocess.run(['squeue',
                            '--name=buildkite',
                            '--noheader',
                            '--format=%k,%A'],
                        stdout=subprocess.PIPE)

        current_jobs = dict()

        for line in squeue.stdout.decode('utf-8').splitlines():
            buildkite_url, slurm_job_id = line.split(',', 1)
            current_jobs.setdefault(buildkite_url, []).append(slurm_job_id)

        for url in current_jobs.keys():
            if len(current_jobs[url]) > 1:
                logger.warning(f"{url} has multiple slurmjobs: {current_jobs[url]})")

        return current_jobs

    def format_resource(self, key, value):
        key = key.split('slurm_', 1)[1].replace('_', '-')
        # If the value is 'true', we know this is a flag instead of an argument
        if value.lower() == 'true':
            return f"--{key}"
        else:
            return f"--{key}={value}"

DATABASE_FILE = "jobs.db"  # Dict database, maps from pbs jobid to buildkite job url

class PBSJobScheduler(JobScheduler):
    def submit_job(self, logger, build_log_dir, job):
        job_id = job['id']
        buildkite_url = job['web_url']
        tags = get_buildkite_job_tags(job)
        buildkite_queue = tags['queue']
        
        # TODO: Retried jobs currently append their log to the existing one
        log_file = joinpath(build_log_dir, f"{job_id}.log")

        cmd = [
            'qsub',
            '-V',               # Inherit environment variables
            '-m', 'n',          # No mail
            '-j', 'oe',         # Output stdout and stderr
            '-N', 'buildkite',  # Job name
            '-o',  log_file,
        ]
        pbs_tags = {k: v for k, v in tags.items() if k.startswith('pbs_')}
        for key, value in pbs_tags.items():
            cmd.extend(self.format_resource(key.split('pbs_', 1)[1], value))

        default_reservation = DEFAULT_RESERVATIONS.get(buildkite_queue, None)
        if "pbs_A" not in pbs_tags and default_reservation:
            cmd.extend(["-A", default_reservation])

        if 'pbs_q' not in pbs_tags:
            if gpu_is_requested(pbs_tags):
                default_pbs_queue = DEFAULT_GPU_PARTITIONS[buildkite_queue]
            else:
                default_pbs_queue = DEFAULT_PARTITIONS[buildkite_queue]
            cmd.extend(["-q", default_pbs_queue])

        if 'pbs_l_walltime' not in pbs_tags:
            cmd.extend(["-l", f"walltime={DEFAULT_TIMELIMIT}"])
        cmd.extend(["--", joinpath(BUILDKITE_PATH, 'bin/schedule_job.sh'), job_id])

        modules = tags.get('modules', "")
        if modules != "":
            cmd.append(modules)

        logger.debug(f"PBS command: {' '.join(cmd)}")
        try:
            ret = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"PBS job submission failed: {(' ').join(e.cmd)}")
            logger.error(f"Return code: {e.returncode}")
            logger.error(f"stderr: {e.stderr}")
            return None


        pbs_job_id = self.parse_job_id(ret.stdout)
        if pbs_job_id:
            logger.info(f"Submitted PBS job {pbs_job_id}, log {log_file}")
            try:
                with dbm.open(DATABASE_FILE, 'w') as db:
                    db[buildkite_url] = pbs_job_id
            except dbm.error as e:
                logger.error(f"Failed to add job to database: {e}")
            return pbs_job_id
        else:
            logger.error(f"Failed to parse PBS job ID from output: {ret.stdout}")
            return None

    # Returns all current jobs, removing those which don't have a running PBS job    
    def current_jobs(self, logger):
        current_jobs = {}
        try:
            with dbm.open(DATABASE_FILE, 'c') as db:
                for k in db.keys():
                    current_jobs[k.decode()] = db[k].decode()
        except dbm.error as e:
            logger.error(f"Failed to read from database: {e}")
            return {}

        try:
            default_pbs_server = DEFAULT_PBS_SERVERS[BUILDKITE_QUEUE]
            qstat_output = subprocess.check_output(['qstat', f'@{default_pbs_server}'], universal_newlines=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to retrieve PBS job status: {e}")
            return current_jobs

        # Get active PBS job table, strip away header and footer
        all_pbs_jobs = qstat_output.split('\n')[2:-1]
        active_pbs_jobs = []
        for job in all_pbs_jobs:
            [job_id, job_name, user, time, state, queue] = job.split()
            if job_name == "buildkite":
                active_pbs_jobs.append(job_id.split('.')[0])
        logger.debug(f"Active PBS jobs: {active_pbs_jobs}")
        # Remove jobs that are no longer running on PBS
        try:
            with dbm.open(DATABASE_FILE, 'w') as db:
                for job_id in list(current_jobs.values()):
                    if job_id not in active_pbs_jobs:
                        logger.debug(f"Removing completed job from database: {job_id}")
                        for k in db.keys():
                            if db[k].decode() == job_id:
                                del current_jobs[k.decode()]
                                del db[k]
                                break

        except dbm.error as e:
            logger.error(f"Failed to remove completed jobs from database: {e}")

        return current_jobs

    def cancel_jobs(self, logger, job_ids):
        logger.debug(f"Canceling PBS jobs: {', '.join(job_ids)}")
        cmd = ["qdel"] + job_ids
        
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"Error when canceling jobs: {' '.join(e.cmd)}")
            logger.error(f"Return code: {e.returncode}")
            logger.error(f"stderr: {e.stderr}")
        try:
            with dbm.open(DATABASE_FILE, 'w') as current_jobs:
                for job_id in job_ids:
                    if job_id in current_jobs:
                        del current_jobs[job_id]
                        logger.info(f"Removed job {job_id} from database")
        except dbm.error as e:
            logger.error(f"Failed to update database after canceling jobs: {e}")

    def format_resource(self, key, value):
        if key.startswith('l_'):
            return ["-l", f"{key[2:]}={value}"]
        elif value.lower() == 'true':
            return [f"--{key}"]
        else:
            return [f"-{key}", value]

    def parse_job_id(self, output):
        job_id_match = re.search(r'^(\d+)', output)
        if job_id_match:
            return job_id_match.group(1)
        return None

RUNPOD_DATABASE_FILE = "runpod_jobs"
RUNPOD_API_URL = "https://api.runpod.io/graphql"

# Default RunPod GPU type per number of GPUs requested
DEFAULT_RUNPOD_GPU = "NVIDIA L40S"

class RunPodJobScheduler(JobScheduler):
    def __init__(self):
        self.api_key = os.environ.get('RUNPOD_API_KEY', '')
        self.docker_image = os.environ.get('RUNPOD_DOCKER_IMAGE', '')
        self.agent_token = os.environ.get('BUILDKITE_AGENT_TOKEN', '')
        if not self.agent_token:
            # Parse agent token from buildkite-agent.cfg
            cfg_path = joinpath(BUILDKITE_PATH, 'buildkite-agent.cfg')
            with open(cfg_path, 'r') as f:
                for line in f:
                    if line.startswith('token='):
                        self.agent_token = line.split('=', 1)[1].strip().strip('"')
                        break
        if not self.api_key:
            raise ValueError("RUNPOD_API_KEY environment variable is required for RunPod scheduler")
        if not self.docker_image:
            raise ValueError("RUNPOD_DOCKER_IMAGE environment variable is required (e.g. 'your-registry/clima-buildkite:latest')")

    def _graphql(self, query, variables=None, logger=None):
        payload = {"query": query}
        if variables:
            payload["variables"] = variables
        if logger:
            # Log query without variables (which may contain secrets)
            logger.debug(f"RunPod API request: {payload['query'].strip()}")
        resp = requests.post(
            RUNPOD_API_URL,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            json=payload,
        )
        if logger:
            logger.debug(f"RunPod API response: HTTP {resp.status_code}")
        resp.raise_for_status()
        data = resp.json()
        if logger:
            logger.debug(f"RunPod API response body: {json.dumps(data, default=str)}")
        if "errors" in data:
            raise RuntimeError(f"RunPod API error: {data['errors']}")
        return data

    def _get_active_pods(self, logger=None):
        """Return a dict of {pod_name: pod_id} for all active RunPod pods."""
        query = "query { myself { pods { id name desiredStatus } } }"
        result = self._graphql(query, logger=logger)
        return {
            pod["name"]: pod["id"]
            for pod in result["data"]["myself"]["pods"]
        }

    def submit_job(self, logger, build_log_dir, job):
        job_id = job['id']
        buildkite_url = job['web_url']
        tags = get_buildkite_job_tags(job)
        logger.debug(f"RunPod submit_job: job_id={job_id}, tags={tags}")

        # Check if a pod for this job already exists on RunPod
        pod_name = f"buildkite-{job_id[:8]}"
        try:
            active_pods = self._get_active_pods(logger)
            logger.debug(f"RunPod active pods: {active_pods}")
            if pod_name in active_pods:
                existing_id = active_pods[pod_name]
                logger.info(f"Pod already exists for job {job_id}: {existing_id}, skipping deploy")
                # Ensure it's tracked in the local database
                try:
                    with dbm.open(RUNPOD_DATABASE_FILE, 'c') as db:
                        db[buildkite_url] = existing_id
                except dbm.error:
                    pass
                return existing_id
        except Exception as e:
            logger.warning(f"Could not check for existing pods: {e}, proceeding with deploy")

        # Extract RunPod-specific tags (runpod_gpu, runpod_gpus, runpod_volume, etc.)
        runpod_tags = {k: v for k, v in tags.items() if k.startswith('runpod_')}
        gpu_type = runpod_tags.get('runpod_gpu', DEFAULT_RUNPOD_GPU)
        gpu_count = int(runpod_tags.get('runpod_gpus', '1'))
        volume_size = int(runpod_tags.get('runpod_volume_gb', '0'))
        modules = tags.get('modules', '')

        env_vars = {
            "BUILDKITE_AGENT_TOKEN": self.agent_token,
            "BUILDKITE_JOB_ID": job_id,
            "BUILDKITE_QUEUE": "runpod",
            "RUNPOD_API_KEY": self.api_key,
        }
        github_ssh_key = os.environ.get('GITHUB_SSH_KEY', '')
        if github_ssh_key:
            env_vars["GITHUB_SSH_KEY"] = github_ssh_key
        if modules:
            env_vars["BUILDKITE_MODULES"] = modules

        # Convert env dict to RunPod format
        env_list = [{"key": k, "value": v} for k, v in env_vars.items()]
        logger.debug(f"RunPod deploy config: image={self.docker_image}, gpu={gpu_type} x{gpu_count}, volume={volume_size}GB, containerDisk=40GB")

        query = """
        mutation podFindAndDeployOnDemand($input: PodFindAndDeployOnDemandInput!) {
            podFindAndDeployOnDemand(input: $input) {
                id
                name
                desiredStatus
            }
        }
        """
        variables = {
            "input": {
                "name": f"buildkite-{job_id[:8]}",
                "imageName": self.docker_image,
                "gpuTypeId": gpu_type,
                "gpuCount": gpu_count,
                "volumeInGb": volume_size,
                "containerDiskInGb": 40,
                "env": env_list,
            }
        }

        try:
            result = self._graphql(query, variables, logger=logger)
            pod = result["data"]["podFindAndDeployOnDemand"]
            pod_id = pod["id"]
            logger.info(f"RunPod pod deployed: {pod_id} for job {job_id}, GPU: {gpu_type} x{gpu_count} - https://www.console.runpod.io/pods?id={pod_id}")

            # Track the pod in our local database
            try:
                with dbm.open(RUNPOD_DATABASE_FILE, 'c') as db:
                    db[buildkite_url] = pod_id
            except dbm.error as e:
                logger.error(f"Failed to add RunPod job to database: {e}")

            return pod_id

        except Exception as e:
            logger.error(f"RunPod pod deployment failed for job {job_id}: {e}")
            return None

    def current_jobs(self, logger):
        current_jobs = {}
        try:
            with dbm.open(RUNPOD_DATABASE_FILE, 'c') as db:
                for k in db.keys():
                    current_jobs[k.decode()] = db[k].decode()
        except dbm.error as e:
            logger.error(f"Failed to read RunPod job database: {e}")
            return {}

        logger.debug(f"RunPod local database entries: {current_jobs}")

        # Query RunPod for active pods to prune completed ones
        # and catch any pods the local db missed
        try:
            active_pods = self._get_active_pods(logger)
            active_pod_ids = set(active_pods.values())
        except Exception as e:
            logger.error(f"Failed to query RunPod pods: {e}")
            return current_jobs

        logger.debug(f"RunPod active pods: {active_pods}")

        # Remove db entries whose pods no longer exist on RunPod
        try:
            with dbm.open(RUNPOD_DATABASE_FILE, 'w') as db:
                for url, pod_id in list(current_jobs.items()):
                    if pod_id not in active_pod_ids:
                        logger.debug(f"Removing completed RunPod pod from database: {pod_id}")
                        del db[url.encode()]
                        del current_jobs[url]
        except dbm.error as e:
            logger.error(f"Failed to prune RunPod job database: {e}")

        # Add any active "buildkite-*" pods not in our db
        # (covers pods deployed before a db crash or manual intervention)
        db_pod_ids = set(current_jobs.values())
        for pod_name, pod_id in active_pods.items():
            if pod_name.startswith("buildkite-") and pod_id not in db_pod_ids:
                # Use pod_name as a placeholder URL key so poll.py won't re-submit
                placeholder = f"runpod://{pod_name}"
                current_jobs[placeholder] = pod_id
                logger.info(f"Recovered untracked RunPod pod: {pod_name} ({pod_id})")
                try:
                    with dbm.open(RUNPOD_DATABASE_FILE, 'c') as db:
                        db[placeholder] = pod_id
                except dbm.error:
                    pass

        return current_jobs

    def cleanup_stale_pods(self, logger, active_buildkite_urls):
        """Terminate RunPod pods whose Buildkite jobs are no longer scheduled or running.

        Called by the poller after processing builds. active_buildkite_urls is the
        set of job web_urls that are still in a 'scheduled' or 'running' state.
        Pods not associated with any active job are terminated.
        """
        try:
            with dbm.open(RUNPOD_DATABASE_FILE, 'c') as db:
                for k in list(db.keys()):
                    url = k.decode()
                    pod_id = db[k].decode()
                    if url not in active_buildkite_urls:
                        logger.info(f"Cleaning up stale RunPod pod {pod_id} (job no longer active: {url})")
                        self._terminate_pod(logger, pod_id)
        except dbm.error as e:
            logger.error(f"Failed during stale pod cleanup: {e}")

    def cancel_jobs(self, logger, job_ids):
        # job_ids here are pod IDs (strings, not lists)
        for pod_id in job_ids:
            # Handle both string and list values from current_jobs
            if isinstance(pod_id, list):
                for p in pod_id:
                    self._terminate_pod(logger, p)
            else:
                self._terminate_pod(logger, pod_id)

    def _terminate_pod(self, logger, pod_id):
        query = """
        mutation podTerminate($input: PodTerminateInput!) {
            podTerminate(input: $input)
        }
        """
        try:
            self._graphql(query, {"input": {"podId": pod_id}}, logger=logger)
            logger.info(f"Terminated RunPod pod: {pod_id}")
        except Exception as e:
            logger.error(f"Failed to terminate RunPod pod {pod_id}: {e}")

        try:
            with dbm.open(RUNPOD_DATABASE_FILE, 'w') as db:
                for k in db.keys():
                    if db[k].decode() == pod_id:
                        del db[k]
                        break
        except dbm.error as e:
            logger.error(f"Failed to remove pod {pod_id} from database: {e}")


# Detect job scheduler by checking system executables and files.
def get_job_scheduler():
    # RunPod queue does not need local HPC tools — use the RunPod API
    if BUILDKITE_QUEUE == "runpod":
        return RunPodJobScheduler()

    # Check for SLURM
    if any([
        shutil.which('sinfo'),
        shutil.which('srun'),
        shutil.which('sbatch'),
        os.path.exists('/etc/slurm/slurm.conf')
    ]):
        return SlurmJobScheduler()

    # Check for PBS
    if any([
        shutil.which('qstat'),
        shutil.which('pbsnodes'),
        shutil.which('qsub'),
    ]):
        return PBSJobScheduler()

    raise ValueError("Could not detect job scheduler.")
