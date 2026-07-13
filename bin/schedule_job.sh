#!/bin/bash

PATH="${BUILDKITE_PATH}/bin:$PATH"

# Buildkite job UUID. Slurm/PBS pass it as $1; Spur's sbatch forwards no script
# args, so fall back to the job name (submitted as bk_<uuid>).
JOBID="${1:-${SLURM_JOB_NAME#bk_}}"

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
  --name "$BUILDKITE_QUEUE-$JOBID-%n" \
  --config "${BUILDKITE_PATH}/buildkite-agent.cfg" \
  --acquire-job "$JOBID" \
  --tags "$TAGS"
