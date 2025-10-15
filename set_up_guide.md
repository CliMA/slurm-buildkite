## Slurm-Buildkite Set Up Guide

### Setup

This guide will teach you how to get slurm-buildkite running on your Slurm or PBS cluster. It is based off of Buildkite's [Linux agent setup guide.](https://buildkite.com/docs/agent/v3/linux) Review it for more information on Buildkite agents.

First, clone the slurm-buildkite repository to your target directory and `cd` into it. This will be 

Either use an existing personal token or create one [here](https://buildkite.com/user/api-access-tokens/new). Copy this token into a new file in the repo called `.buildkite_token`.

Use this token to install the Buildkite agent:
```
TOKEN=.buildkite_token bash -c "`curl -sL https://raw.githubusercontent.com/buildkite/agent/main/install.sh`"
```

From the buildkite-agent install directory (probably `~/.buildkite-agent`), copy over:
- `bin/buildkite-agent`
	- `cp ~/.buildkite-agent/bin/buildkite-agent bin`
- `buildkite-agent.cfg`
	- `cp ~/.buildkite-agent/buildkite-agent.cfg .`

Now, there are several files to modify:

#### buildkite-agent.cfg
This is the configuration file for the Buildkite agent.
1. Set the agent token, which authorizes the agent to attach to waiting jobs. This is ideally done by creating a new token on [Buildkite](https://buildkite.com/docs/agent/v3/tokens#create-a-token). Copy the token and paste it after `token=` in the file.
2. Set `hooks-path="$BUILDKITE_PATH/hooks"`. The agent will interpolate `$BUILDKITE_PATH` to your local slurm-buildkite directory when it runs. [Hooks](https://buildkite.com/docs/agent/v3/hooks), stored within your local slurm-buildkite directory, are scripts that run at steps in each job's lifecycle. Each file runs for a certain hook.
3. Set `plugins-path="$BUILDKITE_PATH/plugins"`. We do not use plugins, but they could be stored here in the future.
4. Set `build-path` to your slurm-buildkite folder. This is the path where builds will run from. On the Clima GPU server, it is `/scratch/clima/slurm-buildkite`.
5. It may be useful to set `no-plugins=true` and `no-color=true`, which can be done by uncommenting their lines in the file.


#### bin/cron.sh

Add an entry for the `case` statement using your cluster's hostname. If there are multiple nodes, you may want to use a regex to match all possible hostnames.
Within the entry, set `BUILDKITE_PATH` and `BUILDKITE_QUEUE`. `BUILDKITE_PATH` is the path to your slurm-buildkite folder. `BUILDKITE_QUEUE` is your cluster's Buildkite queue name and it is used to filter for the jobs that will run on your cluster.

Lastly, check if an extra bashrc_location is needed.

#### bin/job_schedulers.py

Add entries for:
- `DEFAULT_PARTITIONS`: Map from buildkite queue to slurm partition or PBS queue
- `DEFAULT_GPU_PARTITIONS`: Map from buildkite queue to GPU slurm partition or PBS queue
- `DEFAULT_RESERVATIONS`: Map from buildkite queue to HPC reservation name
- `NO_RESERVATION_QUEUES`: For clusters with no default reservations


#### hooks/environment

We need to ensure that a temporary directory is created on all job nodes.
Add an entry for the `case` statement using your cluster's Buildkite queue. 
Within this entry, create a directory called TMPDIR on all nodes by executing `mkdir $TMPDIR`.
`pdsh` is likely the simplest way to accomplish this.
If this causes errors, on Slurm you can use `srun` and on PBS you can use `pbsdsh` to run `mkdir $TMPDIR` on all nodes

If this requires a lot of code, you can tuck it away by `source`-ing a file in `cluster_environments`. An example of this can be found for the derecho queue.

#### `hooks/pre-exit`
Ensure that previously created TMPDIRs. As before, this can either be done with  `pdsh`, `srun` (with Slurm), or `pbsdsh` (with PBS).

#### Optional: hooks/pre-command
- Ensure that output folders have proper permissions

### Testing

You can test this setup by setting the `BUILDKITE_QUEUE` to `test` and manually running the cronjob `bin/cron.sh`. Logs from the cron job will be written to `logs/YYYY-MM-DD/cron`. 

To test CUDA-aware MPI, you can run the testing script `bin/test_cuda_mpi.jl` within an MPI job. This currently tests for CUDA devices, MPI, working MPI with CUDA, and working MPI with CUDA ensuring peer-to-peer transfer.


Once you have tested the system manually, you can use cron to run the polling script every minute:
On the proper node, run `crontab -e` to pull up your cron jobs.
On a new line, add `*/1 * * * * /bin/bash -l path/to/bin/cron.sh`. 
Be aware that a cron job will not have many of the typical startup environment variables.
If this does not work, you can debug by adding ` >> cron.log 2>&1` to the end of the line or by running the script manually. 
We have not tested concurrent database access and undefined behavior may occur if you run it concurrently.