#!/bin/bash

PATH="${BUILDKITE_PATH}/bin:$PATH"

# For PBS jobs, override TMPDIR before starting the agent.
# PBS sets TMPDIR to /var/tmp/pbs.* which can be cleaned up mid-job,
# causing the agent's hook wrapper files to disappear.
if [ -n "${PBS_JOBID:-}" ]; then
    export TMPDIR="$SCRATCH/pbs-${PBS_JOBID}"
    mkdir -p "$TMPDIR"
fi

# Modules loaded here work in buildkite, but it is best to load modules
# within the agent once the cluster-specific script has been sourced

# queue and modules are used for the environment hook, and error is used for the error hook
# the rest are unused
TAGS="queue=${BUILDKITE_QUEUE}"
if [ $# -ge 2 ]; then
    TAGS="$TAGS,modules=$2"
fi
if [ $# -ge 3 ]; then
    TAGS="$TAGS,error=$3"
fi

ls -l "${BUILDKITE_PATH}/bin/buildkite-agent"

"${BUILDKITE_PATH}/bin/buildkite-agent" start \
  --name "$BUILDKITE_QUEUE-$1-%n" \
  --config "${BUILDKITE_PATH}/buildkite-agent.cfg" \
  --acquire-job "$1" \
  --tags "$TAGS"
