#!/bin/bash
#SBATCH --time=01:05:00
#SBATCH --job-name=buildkite
#SBATCH --reservation=clima

BUILDKITE_PATH=/groups/esm/buildkite

${BUILDKITE_PATH}/bin/buildkite-agent start \
  --name "central-$1-%n" \
  --config "${BUILDKITE_PATH}/buildkite-agent.cfg" \
  --acquire-job "$2" \
  --tags "jobid=${SLURM_JOB_ID},ntasks=${SLURM_NTASKS}"
