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

# Clone CliMA repos into /clima in the background (interactive mode only)
if [ -z "${BUILDKITE_AGENT_TOKEN:-}" ]; then
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
        for repo in "${REPOS[@]}"; do
            name="${repo##*/}"
            dest="/clima/${name}"
            if [ ! -d "$dest" ]; then
                echo "Cloning $repo..." >> "$CLONE_LOG"
                git clone --depth=1 "https://github.com/${repo}.git" "$dest" >> "$CLONE_LOG" 2>&1 || true
            fi
        done
        for repo in "${REPOS[@]}"; do
            name="${repo##*/}"
            dest="/clima/${name}"
            if [ -f "$dest/Project.toml" ]; then
                echo "Instantiating $name..." >> "$CLONE_LOG"
                julia --project="$dest" -e 'import Pkg; Pkg.instantiate()' >> "$CLONE_LOG" 2>&1 || true
            fi
        done
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
