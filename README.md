# Buildkite on Slurm

This allows us to run Buildkite agents on our Slurm cluster.

We poll the Buildkite API (via `bin/poll.py`) from a cron job running on the login node (`bin/cron.sh`)

When there are new scheduled builds, then for each job we first check if it is in the slurm queue (via the Slurm job comment), and if not create a new slurm job that runs an agent with the `--acquire-job` option, so as to ensure there is a 1-1 correspondence between Buildkite jobs and Slurm jobs. This will quit once completed or is cancelled, terminating the Slurm job.


# Passing options to Slurm

Any options in the agent metadata block which are prefixed with `slurm_` are passed to [`sbatch`](https://slurm.schedmd.com/sbatch.html): underscores `_` are converted to hyphens, and the value can be left blank for options which don't have values. For example

```
agents:
  config: cpu
  queue: central
  slurm_nodes: 1
  slurm_tasks_per_node: 2
  slurm_exclusive:
```
would pass the options `--nodes=1 --tasks-per-node=2 --exclusive`.
