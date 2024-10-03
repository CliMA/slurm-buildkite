#!/bin/bash
#SBATCH --time=01:05:00
#SBATCH --job-name=buildkite
#SBATCH --reservation=clima

PATH="${BUILDKITE_PATH}/bin:$PATH"

# queue and modules are used for the environment hook, the rest are unused
TAGS="jobid=${SLURM_JOB_ID},queue=${BUILDKITE_QUEUE},ntasks=${SLURM_NTASKS}"
if [ $# -ge 2 ]; then
    TAGS="$TAGS,modules=$2"
fi

${BUILDKITE_PATH}/bin/buildkite-agent start \
  --name "$BUILDKITE_QUEUE-$1-%n" \
  --config "${BUILDKITE_PATH}/buildkite-agent.cfg" \
  --acquire-job "$1" \
  --tags "$TAGS"
