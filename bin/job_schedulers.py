import subprocess
import os
import logging
from os.path import join as joinpath, isfile

DEFAULT_SCHEDULER = os.environ.get('JOB_SYSTEM', 'slurm')
DEFAULT_TIMELIMIT = '1:05:00'

# Map from buildkite queue to slurm partition
DEFAULT_PARTITIONS = {"derecho": "preempt", "clima": "batch", "new-central": "expansion"}
DEFAULT_GPU_PARTITIONS = {"derecho": "preempt", "clima": "batch", "new-central": "gpu"}

# Map from buildkite queue to slurm reservation
DEFAULT_RESERVATIONS = {"new-central": "clima"}

# Sanitize a pipeline name to use it in a URL
# Lowers and replaces any groups of non-alphanumeric character with a '-'
def sanitize_pipeline_name(name):
    return re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')

def build_url(pipeline_name, build_num):
    return f"https://buildkite.com/clima/{sanitize_pipeline_name(pipeline_name)}/builds/{build_num}"

def get_buildkite_job_tags(job):
    agent_query_rules = job.get('agent_query_rules', [])
    agent_query_rules = {item.split('=')[0]: item.split('=')[1] for item in agent_query_rules}
    return agent_query_rules

def gpu_is_requested(args, agent_query_rules):
    # Just find the word "gpu" in the tag or in its value. It might be a very
    # wide filter...
    gpu_in_args = any("gpu" in s for s in args)
    gpu_in_values = any("gpu" in agent_query_rules[key] for key in args)
    return gpu_in_args or gpu_in_values

class JobScheduler:
    def submit_job(self, agent_queue, log_dir, job):
        raise NotImplementedError("Subclass must implement current_jobs")

    def cancel_jobs(self, job_ids):
        raise NotImplementedError("Subclass must implement current_jobs")

    def current_jobs(self):
        raise NotImplementedError("Subclass must implement current_jobs")

class SlurmJobScheduler(JobScheduler):
    def submit_job(self, logger, build_log_dir, job):
        job_id = job['id']
        buildkite_url = job['web_url']
        tags = get_buildkite_job_tags(job)

        cmd = [
            'sbatch',
            '--parsable',
            "--job-name=buildkite",
            f'--comment={buildkite_url}',
            f"--output={joinpath(build_log_dir, 'slurm-%j.log')}",
        ]
        slurm_keys = {k: v for k, v in tags.items() if k.startswith('slurm_')}
        for key, value in slurm_keys.items():
            cmd.extend(self.format_resource(key.split('slurm_', 1)[1], value))

        # Set partition depending on if a GPU has been requested
        # Fallback to 'default' if there is no default partition
        agent_queue = tags['queue']
        if gpu_is_requested(slurm_keys, tags):
            default_partition = DEFAULT_GPU_PARTITIONS[agent_queue]
        else:
            default_partition = DEFAULT_PARTITIONS[agent_queue]
        agent_partition = tags.get('partition', default_partition)
        cmd.append(f"--partition={agent_partition}")

        # If the user does not give a reservation, try to use default
        default_reservation = DEFAULT_RESERVATIONS.get(agent_queue, None)
        if "slurm_reservation" not in slurm_keys and default_reservation:
            cmd.append(f"--reservation={default_reservation}")

        use_exclude = agent_query_rules.get('exclude', 'true')
        if use_exclude == 'true' and BUILDKITE_EXCLUDE_NODES:
            cmd.append(f"--exclude={BUILDKITE_EXCLUDE_NODES}")

        if "slurm_time" not in slurm_keys:
            cmd.append(f"--time={DEFAULT_TIMELIMIT}")

        cmd.append(joinpath(BUILDKITE_PATH, 'bin/schedule_job.sh'))
        cmd.append(job_id)

        agent_modules = tag.get('modules', "")
        if agent_modules != "":
            cmd.append(agent_modules)

        logger.debug(f"Slurm command: {' '.join(cmd)}")
        ret = subprocess.run(cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True)

        if ret.returncode != 0:
            # TODO: Run a minimal failing slurm job to return the error to buildkite
            logger.error(
                f"Slurm error during job submission, retcode={ret.returncode}: "
                f"\n{ret.stderr}"
            )
        else:
            slurm_job_id = int(ret.stdout)
            log_path = joinpath(build_log_dir, f'slurm-{slurm_job_id}.log')
            logger.info(f"Slurm job submitted, ID: {slurm_job_id}, log: {log_path}")

    def cancel_jobs(self, logger, job_ids):
        cmd = ['scancel', '--name=buildkite']
        cmd.extend(job_ids)
        ret = subprocess.run(cmd,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                universal_newlines=True)
        if ret.returncode != 0:
            logger.error(
                f"Slurm error when canceling jobs, retcode={ret.returncode}: "
                f"\n{ret.stderr}"
            )
        else:
            logger.info(f"Canceling {len(job_ids)} slurm jobs")
            logger.debug(f"Canceled slurm jobs: {job_ids}")

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

        logger.debug(f"Current jobs: {list(currentjobs.keys())}")
        logger.info(f"Current slurm jobs (submitted or started): {len(current_jobs)}")

        return current_jobs

    def format_resource(key, value):
        # If the value is 'true', we know this is a flag instead of an argument
        if value.lower() == 'true':
            cmd.append(f"--{arg}")
        else:
            cmd.append(f"--{arg}={value}")


import dbm

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DATABASE_FILE = "pbs_jobs.db"  # gnu dict database, maps from pbs jobid to buildkite job url

class PBSJobScheduler(JobScheduler):
    def submit_job(self, agent_queue, log_dir, job):
        job_id = job['id']
        buildkite_url = job['web_url']
        tags = get_buildkite_job_tags(job)
        
        logger.info(f"Preparing to submit job {job_id} to PBS queue")
        
        cmd = [
            'qsub',
            '-j', 'oe',
            '-N', 'buildkite',
            '-A', 'UCIT0011',
            f'-o {joinpath(log_dir, "slurm-%j.log")}',
        ]

        pbs_keys = {k: v for k, v in tags.items() if k.startswith('pbs_')}
        for key, value in pbs_keys.items():
            cmd.extend(self.format_resource(key.split('pbs_', 1)[1], value))

        if gpu_is_requested(pbs_keys, tags):
            default_partition = DEFAULT_GPU_PARTITIONS.get(agent_queue, "default")
        else:
            default_partition = DEFAULT_PARTITIONS.get(agent_queue, "default")
        
        agent_partition = tags.get('partition', default_partition)
        cmd.extend(["--partition", agent_partition])

        cmd.extend([joinpath(BUILDKITE_PATH, 'bin/schedule_job.sh'), job_id])

        logger.debug(f"Submitting PBS job with command: {' '.join(cmd)}")

        try:
            ret = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"PBS job submission failed: {e}")
            logger.error(f"Command: {e.cmd}")
            logger.error(f"Return code: {e.returncode}")
            logger.error(f"stdout: {e.stdout}")
            logger.error(f"stderr: {e.stderr}")
            return None

        pbs_job_id = self.parse_job_id(ret.stdout)
        if pbs_job_id:
            logger.info(f"Successfully submitted PBS job {pbs_job_id} for Buildkite job {job_id}")
            try:
                with dbm.open(DATABASE_FILE, 'c') as db:
                    db[pbs_job_id] = buildkite_url
            except dbm.error as e:
                logger.error(f"Failed to add job to database: {e}")
            return pbs_job_id
        else:
            logger.error(f"Failed to parse PBS job ID from output: {ret.stdout}")
            return None

    def cancel_jobs(self, job_ids):
        logger.info(f"Attempting to cancel PBS jobs: {', '.join(job_ids)}")
        cmd = ["qdel"] + job_ids
        
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
            logger.info(f"Successfully cancelled PBS jobs: {', '.join(job_ids)}")
        except subprocess.CalledProcessError as e:
            logger.error(f"Error when canceling jobs: {e}")
            logger.error(f"Command: {e.cmd}")
            logger.error(f"Return code: {e.returncode}")
            logger.error(f"stdout: {e.stdout}")
            logger.error(f"stderr: {e.stderr}")
        
        try:
            with dbm.gnu.open(DATABASE_FILE, 'w') as current_jobs:
                for job_id in job_ids:
                    if job_id in current_jobs:
                        del current_jobs[job_id]
                        logger.info(f"Removed job {job_id} from database")
        except dbm.error as e:
            logger.error(f"Failed to update database after canceling jobs: {e}")

    def current_jobs(self):
        current_jobs = {}
        try:
            with dbm.gnu.open(DATABASE_FILE, 'c') as db:
                for k in db.keys():
                    current_jobs[k.decode()] = db[k].decode()
        except dbm.error as e:
            logger.error(f"Failed to read from database: {e}")
            return {}

        try:
            qstat_output = subprocess.check_output(['qstat', '-f'], universal_newlines=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to retrieve PBS job status: {e}")
            return current_jobs

        qsub_jobs = re.split(r'\n\n(?=Job Id:)', qstat_output)
        active_jobs = {}

        for job in qsub_jobs:
            job_id_match = re.search(r'Job Id: (\S+)', job)
            if job_id_match:
                job_id = job_id_match.group(1)
                if job_id in current_jobs:
                    active_jobs[job_id] = current_jobs[job_id]
                else:
                    logger.info(f"Found new job in PBS queue: {job_id}")
                    active_jobs[job_id] = "Unknown URL"
                    try:
                        with dbm.gnu.open(DATABASE_FILE, 'w') as db:
                            db[job_id] = active_jobs[job_id]
                    except dbm.error as e:
                        logger.error(f"Failed to add new job {job_id} to database: {e}")

        try:
            with dbm.gnu.open(DATABASE_FILE, 'w') as db:
                for job_id in list(current_jobs.keys()):
                    if job_id not in active_jobs:
                        logger.info(f"Removing completed job from database: {job_id}")
                        del db[job_id]
        except dbm.error as e:
            logger.error(f"Failed to remove completed jobs from database: {e}")

        return active_jobs

    def format_resource(key, value):
        if key.startswith('l_'):
            return ["-l", f"{key[2:]}={value}"]
        elif value.lower() == 'true':
            return [f"--{key}"]
        else:
            return [f"--{key}", value]

    def parse_job_id(output):
        job_id_match = re.search(r'^(\d+)', output)
        if job_id_match:
            return job_id_match.group(1)
        return None

def get_job_scheduler(scheduler_type = DEFAULT_SCHEDULER):
    if scheduler_type.lower() == 'slurm':
        return SlurmJobScheduler()
    elif scheduler_type.lower() == 'pbs':
        return PBSJobScheduler()
    else:
        raise ValueError(f"Unsupported job scheduler: {scheduler_type}")
