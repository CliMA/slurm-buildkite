# Buildkite on HPC

Run [Buildkite pipelines](https://buildkite.com/) on an HPC cluster. 
To get started, see our [set-up guide](https://github.com/CliMA/slurm-buildkite/blob/master/set_up_guide.md).

## Design

The basic idea is that each Buildkite job is run inside a scheduled HPC job: the job runs the Buildkite agent with the [`--acquire-job`](https://buildkite.com/docs/agent/v3/cli-start#acquire-job) option, which ensures that only the specific Buildkite job is scheduled, and is terminated and exits once complete.

Some clusters are not web-accessible, so we are unable to use webhooks to schedule their jobs. Instead poll the Buildkite API (via [`bin/poll.py`](https://github.com/CliMA/slurm-buildkite/blob/master/bin/poll.py)) via a cron job running on the cluser login node ([`bin/cron.sh`]((https://github.com/CliMA/slurm-buildkite/blob/master/bin/cron.sh)) at a regular interval (currently every minute). This does the following:

1. Get a list of the Buildkite jobs which are currently queued or running on the cluster.

2. Query the Buildkite API to get a list of all [builds for the organization](https://buildkite.com/docs/apis/rest-api/builds#list-builds-for-an-organization) that are currently scheduled. For each build, and for each job in the build, if the job is not already scheduled on the cluster, then schedule a new job to run [`bin/schedule_job.sh`](https://github.com/CliMA/slurm-buildkite/blob/master/bin/schedule_job.sh).

3. Query the Buildkite API for a list of all builds that are cancelled. For each build and each job in the build, cancel any Slurm jobs with the matching job id.

Unlike regular Buildkite builds, we don't run each job in an isolated environment, so the checkout only happens on the first job (usually the pipeline upload) and the state is shared between all jobs in the build.


## Passing options to Slurm

Any options in the agent metadata block which are prefixed with `slurm_` are passed to [`sbatch`](https://slurm.schedmd.com/sbatch.html): underscores `_` are converted to hyphens.
For arguments without values, they must be set to true.

As an example,
```
agents:
  queue: new-central
  slurm_nodes: 1
  slurm_tasks_per_node: 2
```
would pass the options `--nodes=1 --tasks-per-node=2`.

## Passing options to PBS

Any options prefixed with `pbs_` are passed to `qsub`. Any options prefixed with `pbs_l_` are passed through to `qsub`'s `-l` argument. Underscores are converted to hyphens.

For arguments without values, they must be set to true.

As an example,
```
agents:
    pbs_q: preempt
    pbs_l_select: "2:ngpus=4:ncpus=8"
    pbs_l_walltime: "02:00:00"
```
would pass the options `-q preempt -l select=2:ngpus=4:ncpus=8 -l walltime=02:00:00`
