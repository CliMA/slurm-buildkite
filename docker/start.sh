#!/bin/bash

set -euo pipefail

# SSH key setup
mkdir -p /root/.ssh
if [ -n "${PUBLIC_KEY:-}" ]; then
    echo "$PUBLIC_KEY" >> /root/.ssh/authorized_keys
    chmod 700 /root/.ssh
    chmod 600 /root/.ssh/authorized_keys
fi

# GitHub deploy key for cloning repos
if [ -n "${GITHUB_SSH_KEY:-}" ]; then
    echo "$GITHUB_SSH_KEY" > /root/.ssh/id_ed25519
    chmod 600 /root/.ssh/id_ed25519
    ssh-keyscan -t ed25519 github.com >> /root/.ssh/known_hosts 2>/dev/null
fi

service ssh start

# Stage the artifact depot on /workspace (the volume disk) when available,
# instead of the small container overlay. Everything else still uses the
# /clima-artifacts path via this symlink.
if [ -d /workspace ] && [ ! -e /clima-artifacts ]; then
    mkdir -p /workspace/ClimaArtifacts
    ln -sfn /workspace/ClimaArtifacts /clima-artifacts
fi

# Persist Julia depot and shell history on /workspace so they survive pod
# restarts 
if [ -d /workspace ]; then
    mkdir -p /workspace/.julia
    if [ ! -L /root/.julia ]; then
        if [ -d /root/.julia ]; then
            cp -an /root/.julia/. /workspace/.julia/ 2>/dev/null || true
            rm -rf /root/.julia
        fi
        ln -sfn /workspace/.julia /root/.julia
    fi
    touch /workspace/.bash_history
    if [ ! -L /root/.bash_history ]; then
        rm -f /root/.bash_history
        ln -sfn /workspace/.bash_history /root/.bash_history
    fi
    # Persist /clima (CliMA source clones) on volume too so file mtimes don't
    # reset on stop/resume, which would invalidate the Julia precompile cache.
    if [ ! -L /clima ]; then
        mkdir -p /workspace/clima
        if [ -d /clima ]; then
            cp -an /clima/. /workspace/clima/ 2>/dev/null || true
            # cd out first — Dockerfile sets WORKDIR /clima so bash's cwd
            # starts there. Without this, rm -rf leaves the shell in a
            # dangling cwd until something cd's away.
            cd /
            rm -rf /clima
        fi
        ln -sfn /workspace/clima /clima
    fi
    # Stale precompile pidfiles from the previous Julia processes confuse
    # Pkg.precompile into either waiting or recompiling. None should be live at
    # boot time
    find /workspace/.julia/compiled -name '*.pidfile' -delete 2>/dev/null || true
fi

# Kick off artifact prefetch in the background as early as possible so it
# overlaps with agent registration, job acquisition, and git checkout. The
# pre-command hook blocks on /clima-artifacts/.ready before any Julia step.
if [ -x /usr/local/bin/install-clima-artifacts.sh ] && [ -z "${NO_ARTIFACTS:-}" ]; then
    echo "Starting clima-artifacts prefetch in background (log: /var/log/clima-artifacts.log)"
    /usr/local/bin/install-clima-artifacts.sh > /var/log/clima-artifacts.log 2>&1 &
fi

# AWS Batch exec-args mode: run the command passed via containerOverrides.command
# and exit. Waits for artifact prefetch before exec'ing so Julia finds artifacts.
# Set NO_ARTIFACTS=1 to skip the prefetch and wait entirely.
if [ "$#" -gt 0 ]; then
    echo "Running in exec-args mode: $*"
    if [ -z "${NO_ARTIFACTS:-}" ]; then
        TIMEOUT="${CLIMA_ARTIFACTS_WAIT_TIMEOUT:-1800}"
        ELAPSED=0
        while [ ! -e /clima-artifacts/.ready ] && [ ! -e /clima-artifacts/.failed ]; do
            sleep 2
            ELAPSED=$((ELAPSED + 2))
            if [ "$ELAPSED" -ge "$TIMEOUT" ]; then
                echo "ERROR: artifact prefetch timed out after ${TIMEOUT}s"
                exit 1
            fi
        done
        if [ -e /clima-artifacts/.failed ]; then
            echo "ERROR: artifact prefetch failed — see /var/log/clima-artifacts.log"
            exit 1
        fi
    fi
    exec "$@"
fi

# Clone CliMA repos into /clima in the background (interactive mode only)
if [ "$#" -eq 0 ]; then
    CLONE_LOG="/tmp/clone.log"
    echo "Running in interactive mode — cloning repos in background"
    echo "Follow clone progress with: tail -f $CLONE_LOG"
    REPOS=(
        CliMA/ClimaCoupler.jl
        CliMA/ClimaAtmos.jl
        CliMA/ClimaCore.jl
        CliMA/ClimaLand.jl
    )
    (
        until curl -sf --max-time 5 https://github.com > /dev/null 2>&1; do
            echo "Waiting for network..." >> "$CLONE_LOG"
            sleep 2
        done
        pids=()
        for repo in "${REPOS[@]}"; do
            name="${repo##*/}"
            dest="/clima/${name}"
            if [ ! -d "$dest" ]; then
                echo "Cloning $repo..." >> "$CLONE_LOG"
                git clone --filter=blob:none \
                    "https://github.com/${repo}.git" "$dest" \
                    >> "$CLONE_LOG" 2>&1 &
                pids+=($!)
            fi
        done
        for pid in "${pids[@]}"; do wait "$pid" || true; done
        echo "Done." >> "$CLONE_LOG"
    ) &

    tail -f /dev/null
    exit 0
fi


# Write agent token to config
sed -i "s/token=\"xxx\"/token=\"${BUILDKITE_AGENT_TOKEN}\"/" \
    /etc/buildkite-agent/buildkite-agent.cfg

terminate_pod() {
    echo "Terminating pod..."
    if [ -n "${RUNPOD_API_KEY:-}" ] && [ -n "${RUNPOD_POD_ID:-}" ]; then
        curl -s --retry 3 --retry-delay 5 -X POST "https://api.runpod.io/graphql" \
            -H "Content-Type: application/json" \
            -H "Authorization: Bearer $RUNPOD_API_KEY" \
            -d "{\"query\":\"mutation { podTerminate(input: { podId: \\\"$RUNPOD_POD_ID\\\" }) }\"}"
        echo "Pod termination requested."
    else
        echo "WARNING: Missing RUNPOD_API_KEY or RUNPOD_POD_ID — cannot self-terminate"
    fi
}

if [ -n "${BUILDKITE_JOB_ID:-}" ]; then
    # On-demand mode: run a single job, then terminate the pod
    echo "Running in acquire-job mode for job: $BUILDKITE_JOB_ID"

    # Watchdog: terminate the pod if the job exceeds the timeout
    RUNPOD_TIMEOUT="${RUNPOD_TIMEOUT:-3900}"  # default 65 minutes (matches DEFAULT_TIMELIMIT)
    (
        sleep "$RUNPOD_TIMEOUT"
        echo "ERROR: Pod exceeded timeout of ${RUNPOD_TIMEOUT}s. Forcing termination."
        terminate_pod
        kill $$ 2>/dev/null  # kill the main script
    ) &
    WATCHDOG_PID=$!

    # Terminate pod regardless of how the agent exits (success, failure, or crash)
    trap 'kill $WATCHDOG_PID 2>/dev/null; terminate_pod' EXIT

    TAGS="queue=${BUILDKITE_QUEUE:-runpod}"
    if [ -n "${BUILDKITE_MODULES:-}" ]; then
        TAGS="$TAGS,modules=$BUILDKITE_MODULES"
    fi

    buildkite-agent start \
        --name "runpod-${RUNPOD_POD_ID:-unknown}-%n" \
        --acquire-job "$BUILDKITE_JOB_ID" \
        --tags "$TAGS"

    echo "Job completed."
    # EXIT trap handles termination
else
    # Persistent mode: long-running agent (for debugging or always-on use)
    echo "Running in persistent agent mode"
    echo "tags=\"queue=${BUILDKITE_QUEUE:-runpod},cuda=12.4,julia=true\"" \
        >> /etc/buildkite-agent/buildkite-agent.cfg

    if [ -n "${RUNPOD_POD_ID:-}" ]; then
        echo "name=\"runpod-${RUNPOD_POD_ID}\"" \
            >> /etc/buildkite-agent/buildkite-agent.cfg
    fi

    buildkite-agent start &
    tail -f /dev/null
fi
