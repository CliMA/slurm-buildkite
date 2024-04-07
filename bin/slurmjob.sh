#!/bin/bash
#SBATCH --time=01:05:00
#SBATCH --job-name=buildkite
#SBATCH --reservation=clima

BUILDKITE_PATH=${BUILDKITE_PATH:=/groups/esm/slurm-buildkite}
BUILDKITE_QUEUE=${BUILDKITE_QUEUE:=new-central}
PATH="${BUILDKITE_PATH}/bin:$PATH"

TAGS="jobid=${SLURM_JOB_ID},queue=${BUILDKITE_QUEUE},ntasks=${SLURM_NTASKS}"
if [ $# -ge 2 ]; then
    TAGS="$TAGS,modules=$2"
fi


${BUILDKITE_PATH}/bin/buildkite-agent start \
  --name "$BUILDKITE_QUEUE-%n" \
  --config "${BUILDKITE_PATH}/buildkite-agent.cfg" \
  --acquire-job "$1" \
  --tags "$TAGS"
