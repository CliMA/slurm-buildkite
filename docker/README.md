# Runpod Guide

## Account Setup

1. Get invited to the team via email
2. Add an SSH key in **Account > Settings > SSH public keys** — [how to generate one](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/generating-a-new-ssh-key-and-adding-it-to-the-ssh-agent#generating-a-new-ssh-key)

## Starting a Pod

1. Go to the [deployment link](https://console.runpod.io/deploy?template=gd5u5qpvri&ref=oqgbugey)
2. Under **Select an instance**, check **Global networking**
3. Select GPU type: **L40S**
4. Under **Storage configuration**, click **Volume disk**
5. Click **Deploy On-Demand** — the pod takes a few minutes to start

## Connecting

SSH using the command shown on the pod page, substituting your key:

```bash
ssh d7h8gkteb3739c-644121cc@ssh.runpod.io -i ~/.ssh/runpod
```

To avoid typing this each time, add an entry to `~/.ssh/config`:

```
Host runpod
  HostName ssh.runpod.io
  User sgmnl1q9igmfhg-644118ea
  IdentityFile ~/.ssh/runpod
```

Then connect with just `ssh runpod`.

## What's in the Container

- Julia 1.10, 1.11, 1.12 (default: 1.12)
- CliMA repositories cloned into `/clima/` on startup
- tmux, vim, htop, rsync
- VS Code tunnel support (`code tunnel`)

## VS Code

To connect via VS Code, run `code tunnel` inside the pod and follow the prompt. See also [Runpod's IDE guide](https://docs.runpod.io/pods/configuration/connect-to-ide).

## Copying Files

Use `rsync` over SSH:

```bash
rsync -avz runpod:/clima/ClimaAtmos.jl/output/ ./output/
```

If `sftp`/`scp` are unavailable (e.g. the pod's SSH server doesn't support subsystems), use `runpodctl` instead. For large folders, zip first to reduce transfer size over the relay:

```bash
# On the pod — zip, then send (runpodctl prints a transfer code)
tar -czf output.tar.gz output/
runpodctl send output.tar.gz
# => Sending output.tar.gz | Code: 8-fluffy-tiger-4

# On your local machine — paste the code printed above
runpodctl receive 8-fluffy-tiger-4
tar -xzf output.tar.gz
```

`runpodctl` is pre-installed on Runpod pods. Install it locally with:

```bash
brew install runpod/runpodctl/runpodctl   # macOS
# or download from https://github.com/runpod/runpodctl/releases
```

## Stopping

Click **Stop** on the Runpod website when done. Storage continues to be charged, but lets you quickly resume the pod later.

---

# Runpod Buildkite Container

Docker image for running Buildkite CI jobs on Runpod GPU instances. Based on `nvidia/cuda:12.4.1-cudnn-devel-ubuntu22.04` with Julia and the Buildkite agent pre-installed.

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

- `BUILDKITE_AGENT_TOKEN`: Buildkite agent registration token. Unset → interactive mode
- `BUILDKITE_JOB_ID`: Job to acquire. Set with token → on-demand mode; unset with token → persistent agent mode
- `BUILDKITE_QUEUE`: Queue tag (default: `runpod`)
- `RUNPOD_API_KEY`: Used for pod self-termination after job completion
- `GITHUB_SSH_KEY`: Private SSH key for cloning repos from GitHub
- `PUBLIC_KEY`: SSH public key for connecting to the container
- `CLIMA_ARTIFACTS`: Comma-separated artifact names to prefetch (subset of the manifest). Unset → prefetch all.
- `CLIMA_ARTIFACTS_WAIT_TIMEOUT`: Seconds to wait for artifact prefetch before failing (default: 1800). Increase to 7200 for cold EFS.
- `NO_ARTIFACTS`: Set to any non-empty value to skip artifact prefetch entirely and exec the command immediately. Useful for local testing.
- `CLIMA_ARTIFACTS_PROJECTS`: Comma-separated project dirs; their `Artifacts.toml`-declared names are added to the prefetch set. Bare names like `ClimaLand` resolve to `/clima/ClimaLand.jl`; absolute paths are used as-is. Example: `ClimaLand,ClimaAtmos,ClimaCoupler`. Unset → prefetch all.

## Cloning Repositories

CliMA repos are cloned into `/clima/<name>` on pod startup. To add or remove repos, edit the list in `start.sh`.

## Primary use cases

This image exists to serve three workloads. Every mode shares the same foundation: CUDA + Julia + Buildkite agent + the prefetched CliMA artifact mirror, with `/root/.julia` and `/root/.bash_history` migrated onto `/workspace` when a volume disk is mounted.

| Use case | Mode | How it's deployed |
|---|---|---|
| **Interactive development** | Interactive (no agent token) | Manual pod from the Runpod console. SSH in or `code tunnel`. Allocate ≥80 GB volume disk so the depot survives stop/resume. |
| **Buildkite long runs on Runpod** | On-demand acquire-job (token + job id) | A buildkite pipeline tags its steps with `agents: { queue: runpod }`; the slurm-buildkite scheduler (`bin/job_schedulers.py`'s `RunpodJobScheduler`) deploys one pod per job, the agent acquires that job, runs it, pod self-terminates. Set up the pipeline to fit within the 65-min watchdog or override `RUNPOD_TIMEOUT`. |
| **AWS Batch calibration ensembles** | exec-args mode | AWS Batch's `containerOverrides.command` runs `julia` directly after the prefetch finishes — no buildkite agent. See [docs/aws_batch_calibration_setup.md](../docs/aws_batch_calibration_setup.md). |
