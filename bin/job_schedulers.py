import subprocess
import dbm
import os
from os.path import join as joinpath
import re
import shutil
from buildkite import get_buildkite_job_tags, BUILDKITE_EXCLUDE_NODES, BUILDKITE_PATH

DEFAULT_SCHEDULER = os.environ.get('JOB_SYSTEM', 'slurm')
DEFAULT_TIMELIMIT = '1:05:00'

# Map from buildkite queue to slurm partition or PBS queue
DEFAULT_PARTITIONS = {"derecho": "preempt", "test": "batch", "clima": "batch", "new-central": "expansion"}
DEFAULT_GPU_PARTITIONS = {"derecho": "preempt", "test": "batch", "clima": "batch", "new-central": "gpu"}

# Map from buildkite queue to HPC reservation
DEFAULT_RESERVATIONS = {"new-central": "clima", "derecho": "UCIT0011"}

# Search for the word "gpu" in the given dict
def gpu_is_requested(scheduler_tags):
    found = any("gpu" in key or "gpu" in value for key, value in scheduler_tags.items())
    return found

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

        cmd = [
            'sbatch',
            '--parsable',
            "--job-name=buildkite",
            f'--comment={buildkite_url}',
            f"--output={joinpath(build_log_dir, 'slurm-%j.log')}",
        ]
        slurm_keys = {k: v for k, v in tags.items() if k.startswith('slurm_')}
        for key, value in slurm_keys.items():
            cmd.append(self.format_resource(key, value))

        # Set partition depending on if a GPU has been requested
        # Fallback to 'default' if there is no default partition
        queue = tags['queue']
        if gpu_is_requested(slurm_keys):
            default_partition = DEFAULT_GPU_PARTITIONS[queue]
        else:
            default_partition = DEFAULT_PARTITIONS[queue]
        agent_partition = tags.get('partition', default_partition)
        cmd.append(f"--partition={agent_partition}")

        # If the user does not give a reservation, try to use default
        default_reservation = DEFAULT_RESERVATIONS.get(queue, None)
        if "slurm_reservation" not in slurm_keys and default_reservation:
            cmd.append(f"--reservation={default_reservation}")

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
        except ValueError as e:
            # Handle case where stdout can't be converted to int
            logger.error(
                f"Invalid job ID returned from Slurm: {result.stdout!r}"
            )
            
    def cancel_jobs(self, logger, job_ids):
        cmd = ['scancel', '--name=buildkite']
        cmd.extend(job_ids)
        try:
            logger.info(f"Canceling {len(job_ids)} Slurm jobs")
            subprocess.run(
                cmd,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True
            )
            logger.debug(f"Canceled Slurm jobs: {job_ids}")
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

DATABASE_FILE = "pbs_jobs.db"  # gnu dict database, maps from pbs jobid to buildkite job url

class PBSJobScheduler(JobScheduler):
    def submit_job(self, logger, build_log_dir, job):
        job_id = job['id']
        buildkite_url = job['web_url']
        tags = get_buildkite_job_tags(job)
        buildkite_queue = tags['queue']
        logger.debug(f"Preparing to submit job {job_id} to PBS queue")
        
        # TODO: Retried jobs currently append their log to the existing one
        log_file = joinpath(build_log_dir, f"{job_id}.log")
        cmd = [
            'qsub', '-V',
            '-j', 'oe',
            '-N', 'buildkite',
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
        logger.debug(f"Submitting PBS job with command: {' '.join(cmd)}")
        try:
            ret = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"PBS job submission failed: {(' ').join(e.cmd)}")
            logger.error(f"Return code: {e.returncode}")
            logger.error(f"stderr: {e.stderr}")
            return None


        pbs_job_id = self.parse_job_id(ret.stdout)
        if pbs_job_id:
            logger.info(f"Successfully submitted PBS job {pbs_job_id}, log {log_file}")
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
            qstat_output = subprocess.check_output(['qstat'], universal_newlines=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to retrieve PBS job status: {e}")
            return current_jobs

        # Find active buildkite jobs, strip away header and footer
        qsub_jobs = qstat_output.split('\n')[2:-1]
        active_pbs_jobs = []
        for job in qsub_jobs:
            [job_id, job_name, user, time, state, queue] = job.split()
            if job_name == "buildkite":
                active_pbs_jobs.append(job_id.split('.'))

        # Remove jobs that are no longer running on PBS
        try:
            with dbm.open(DATABASE_FILE, 'w') as db:
                for job_id in list(current_jobs.keys()):
                    if job_id not in active_pbs_jobs:
                        logger.info(f"Removing completed job from database: {job_id}")
                        del db[job_id]
        except dbm.error as e:
            logger.error(f"Failed to remove completed jobs from database: {e}")

        return current_jobs


    def cancel_jobs(self, logger, job_ids):
        logger.info(f"Attempting to cancel PBS jobs: {', '.join(job_ids)}")
        cmd = ["qdel"] + job_ids
        
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
            logger.info(f"Successfully cancelled PBS jobs: {', '.join(job_ids)}")
        except subprocess.CalledProcessError as e:
            logger.error(f"Error when canceling jobs: {' '.join(e.cmd)}")
            logger.error(f"Return code: {e.returncode}")
            logger.error(f"stderr: {e.stderr}")
        
        try:
            with dbm.gnu.open(DATABASE_FILE, 'w') as current_jobs:
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

# Detect job scheduler by checking system executables and files.
def get_job_scheduler():
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
