# GPU Pod Guide

The same container image runs on both Runpod and Vast.ai, only the deployment step differs.

## Account Setup

Both providers need a team invite, sent by email. Add your SSH public key to your provider account ([how to generate one](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/generating-a-new-ssh-key-and-adding-it-to-the-ssh-agent#generating-a-new-ssh-key)). On Runpod, add the key in **Account > Settings > SSH public keys**. On Vast.ai, add it in **Account > Keys**.

## Starting a Pod

**Runpod**: Go to the [deployment link](https://console.runpod.io/deploy?template=gd5u5qpvri&ref=oqgbugey). Check **Global networking**, select GPU **L40S**, add a **Volume disk**, then **Deploy On-Demand**.

**Vast.ai**: Go to the [template link](https://cloud.vast.ai?ref_id=622688&template_id=a3310e8e568afa4ca1c66211dfaf4495). Pick a GPU offer (e.g. L40S) with at least 80 GB disk, make sure your SSH key is selected, then **Rent**.

The pod takes a few minutes to start.

## Connecting

SSH using the command shown on the pod page, substituting your key. Runpod connects through a relay host. Vast.ai gives a direct IP and port:

```bash
ssh d7h8gkteb3739c-644121cc@ssh.runpod.io -i ~/.ssh/runpod   # Runpod
ssh -p 41234 root@70.1.2.3 -i ~/.ssh/id_ed25519              # Vast.ai
```

Add a matching entry to `~/.ssh/config` to avoid retyping. On Vast.ai the IP and port change each time you launch a new instance, so update it after each launch.

## Copying Files

`rsync` over SSH works on both once you have an `~/.ssh/config` entry:

```bash
rsync -avz runpod:/clima/ClimaAtmos.jl/output/ ./output/
```

On **Vast.ai**, `scp` and `rsync` work directly, or use `vastai copy <instance_id>:/path ./dest` (`pip install vastai`).

On **Runpod**, if `scp` and `sftp` are unavailable, use `runpodctl` instead. It is pre-installed on the pod, and installs locally with `brew install runpod/runpodctl/runpodctl`:

```bash
runpodctl send output.tar.gz        # on the pod, prints a code like 8-fluffy-tiger-4
runpodctl receive 8-fluffy-tiger-4  # on your machine
```

## Stopping

Click **Stop** when you are done, or on Vast.ai run `vastai stop instance <instance_id>`. Storage is still charged while stopped, but you can resume later.

## What's in the Container

- Julia 1.10, 1.11, 1.12 (default: 1.12)
- CliMA repositories cloned into `/clima/` on startup
- tmux, vim, htop, rsync
- VS Code tunnel support (`code tunnel`)

## Workspace and Repositories

On **Runpod**, if you mount a volume disk, the pod keeps your work on `/workspace` so it survives stop and resume. Put your own files under `/workspace` too. Files outside these paths are on the container disk and can be lost when you stop the pod.

On **Vast.ai**, the instance disk persists across stop and resume, so files persist wherever you put them.

On startup the pod clones the CliMA repos into `/clima/` in the background. Follow clone progress with `tail -f /tmp/clone.log`. To change the list, edit `REPOS` in `start.sh`.

## VS Code

To connect via VS Code, run `code tunnel` inside the pod and follow the prompt. See also [Runpod's IDE guide](https://docs.runpod.io/pods/configuration/connect-to-ide).

---

# Buildkite Container

Docker image for running Buildkite CI jobs on GPU instances. Based on `nvidia/cuda:12.4.1-cudnn-devel-ubuntu22.04` with Julia and the Buildkite agent pre-installed. The image runs the same on Runpod and Vast.ai. The on-demand acquire-job automation below is Runpod only.

## Contents

- CUDA 12.4.1 + cuDNN (devel)
- Julia 1.10, 1.11, 1.12 (default: 1.12)
- Buildkite agent
- SSH server
- tmux, vim, htop, less, rsync

## Building

Build on a native linux/amd64 machine (required for precompilation to work correctly):

```bash
docker buildx build --platform linux/amd64 \
    -t nefrathenrici/clima-buildkite:latest --push docker/
```

## Environment Variables

- `BUILDKITE_AGENT_TOKEN`: Buildkite agent registration token. Unset means interactive mode.
- `BUILDKITE_JOB_ID`: Job to acquire. Set with token means on-demand mode. Unset with token means persistent agent mode.
- `BUILDKITE_QUEUE`: Queue tag (default: `runpod`)
- `RUNPOD_API_KEY`: Runpod only. Used for pod self-termination after job completion.
- `GITHUB_SSH_KEY`: Private SSH key for cloning repos from GitHub
- `PUBLIC_KEY`: SSH public key for connecting to the container
- `CLIMA_ARTIFACTS`: Comma-separated artifact names to prefetch (subset of the manifest). Unset means prefetch all.
- `CLIMA_ARTIFACTS_WAIT_TIMEOUT`: Seconds to wait for artifact prefetch before failing (default: 1800). Increase to 7200 for cold EFS.
- `NO_ARTIFACTS`: Set to any non-empty value to skip artifact prefetch entirely and exec the command immediately. Useful for local testing.
- `CLIMA_ARTIFACTS_PROJECTS`: Comma-separated project dirs. Their `Artifacts.toml`-declared names are added to the prefetch set. Bare names like `ClimaLand` resolve to `/clima/ClimaLand.jl`. Absolute paths are used as-is. Example: `ClimaLand,ClimaAtmos,ClimaCoupler`. Unset means prefetch all.

## Cloning Repositories

CliMA repos are cloned into `/clima/<name>` on pod startup. To add or remove repos, edit the list in `start.sh`.

## Primary use cases

This image serves three workloads. Every mode shares the same foundation: CUDA + Julia + Buildkite agent + the prefetched CliMA artifact mirror, with `/root/.julia` and `/root/.bash_history` migrated onto `/workspace` when a volume disk is mounted.

| Use case | Mode | How it's deployed |
|---|---|---|
| **Interactive development** | Interactive (no agent token) | Manual pod from the Runpod or Vast.ai console. SSH in or `code tunnel`. Allocate ≥80 GB disk so the depot survives stop/resume. |
| **Buildkite long runs on Runpod** | On-demand acquire-job (token + job id) | A buildkite pipeline tags its steps with `agents: { queue: runpod }`. The slurm-buildkite scheduler (`bin/job_schedulers.py`'s `RunpodJobScheduler`) deploys one pod per job, the agent acquires that job, runs it, and the pod self-terminates. Set up the pipeline to fit within the 65-min watchdog, or override `RUNPOD_TIMEOUT`. |
| **AWS Batch calibration ensembles** | exec-args mode | AWS Batch's `containerOverrides.command` runs `julia` directly after the prefetch finishes, with no buildkite agent. See [docs/aws_batch_calibration_setup.md](../docs/aws_batch_calibration_setup.md). |
