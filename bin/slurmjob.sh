#!/bin/bash
#SBATCH --time=01:05:00
#SBATCH --job-name=buildkite
#SBATCH --reservation=clima

BUILDKITE_PATH=${BUILDKITE_PATH:=/groups/esm/climaci}
BUILDKITE_QUEUE=${BUILDKITE_QUEUE:=central}

${BUILDKITE_PATH}/bin/buildkite-agent start \
  --name "central-$1-%n" \
  --config "${BUILDKITE_PATH}/buildkite-agent.cfg" \
  --acquire-job "$2" \
  --tags "jobid=${SLURM_JOB_ID},queue=${BUILDKITE_QUEUE},config=$1,ntasks=${SLURM_NTASKS}"
