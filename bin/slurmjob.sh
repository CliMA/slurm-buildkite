#!/bin/bash
#SBATCH --time=01:05:00
#SBATCH --job-name=buildkite
#SBATCH --reservation=clima

# TODO: Remove defaults for BUILDKITE_PATH and BUILDKITE_QUEUE
BUILDKITE_PATH=${BUILDKITE_PATH:=/groups/esm/slurm-buildkite}
BUILDKITE_QUEUE=${BUILDKITE_QUEUE:=new-central}
PATH="${BUILDKITE_PATH}/bin:$PATH"

# TODO: Most of these tags don't seem to be get used
# TODO: We could set the modulepath in the tags here, or it could be determined by queue
TAGS="jobid=${SLURM_JOB_ID},queue=${BUILDKITE_QUEUE},ntasks=${SLURM_NTASKS}"
if [ $# -ge 2 ]; then
    TAGS="$TAGS,modules=$2"
fi

${BUILDKITE_PATH}/bin/buildkite-agent start \
  --name "$BUILDKITE_QUEUE-$1-%n" \
  --config "${BUILDKITE_PATH}/buildkite-agent.cfg" \
  --acquire-job "$1" \
  --tags "$TAGS"
