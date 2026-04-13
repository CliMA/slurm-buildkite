# RunPod Guide

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

To connect via VS Code, run `code tunnel` inside the pod and follow the prompt. See also [RunPod's IDE guide](https://docs.runpod.io/pods/configuration/connect-to-ide).

## Copying Files

Use `rsync` over SSH:

```bash
rsync -avz runpod:/clima/ClimaAtmos.jl/output/ ./output/
```

## Stopping

Click **Stop** on the RunPod website when done. Storage continues to be charged, but lets you quickly resume the pod later.

---

# RunPod Buildkite Container

Docker image for running Buildkite CI jobs on RunPod GPU instances. Based on `nvidia/cuda:12.4.1-cudnn-devel-ubuntu22.04` with Julia and the Buildkite agent pre-installed.

## Contents

- CUDA 12.4.1 + cuDNN (devel)
- Julia 1.10, 1.11, 1.12 (default: 1.12)
- Buildkite agent
- SSH server
- tmux, vim, htop, less, rsync

## Building

Build on a native linux/amd64 machine (required for precompilation to work correctly):

```bash
docker build -t nefrathenrici/clima-buildkite:latest docker/
docker push nefrathenrici/clima-buildkite:latest
```

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `BUILDKITE_AGENT_TOKEN` | Yes | Buildkite agent registration token |
| `BUILDKITE_JOB_ID` | No | Job to acquire. If unset, runs in persistent agent mode |
| `BUILDKITE_QUEUE` | No | Queue tag (default: `runpod`) |
| `RUNPOD_API_KEY` | No | Used for pod self-termination after job completion |
| `GITHUB_SSH_KEY` | No | Private SSH key for cloning repos from GitHub |
| `PUBLIC_KEY` | No | SSH public key for connecting to the container |

## Cloning Repositories

CliMA repos are cloned into `/clima/<name>` on pod startup. To add or remove repos, edit the list in `start.sh`.

## Modes

- **On-demand** (`BUILDKITE_JOB_ID` set): Acquires a single job, runs it, then self-terminates the pod.
- **Persistent** (`BUILDKITE_JOB_ID` unset): Starts a long-running Buildkite agent for debugging.
