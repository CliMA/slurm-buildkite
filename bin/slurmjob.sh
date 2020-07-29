#!/bin/bash
#SBATCH --time=01:05:00
#SBATCH --job-name=buildkite
#SBATCH --reservation=clima

BUILDKITE_PATH=/groups/esm/buildkite
${BUILDKITE_PATH}/bin/buildkite-agent start \
  --config "${BUILDKITE_PATH}/buildkite-agent.cfg" \
  --acquire-job "$1" \
  --tags "jobid=${SLURM_JOB_ID},ntasks=${SLURM_NTASKS}"
