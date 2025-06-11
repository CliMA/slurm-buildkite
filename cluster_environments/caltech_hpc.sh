#!/bin/bash
set -euo pipefail

export MODULEPATH="/groups/esm/modules:$MODULEPATH"
module load git/2.39.3-gcc-11.3.1-zfr3sti

# Default TMPDIR if not set
export TMPDIR="${TMPDIR:-/tmp/slurm-${SLURM_JOB_ID}}"

echo "Creating TMPDIR=$TMPDIR on all nodes: $SLURM_NODELIST"

# Create TMPDIR on all nodes
srun --ntasks-per-node=1 --ntasks="${SLURM_JOB_NUM_NODES}" \
    bash -c "mkdir -p '$TMPDIR' && chmod 700 '$TMPDIR'"
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to create TMPDIR on one or more nodes" >&2
    exit 1
fi

# Verify TMPDIR exists and is a directory on all nodes
srun --ntasks-per-node=1 --ntasks="${SLURM_JOB_NUM_NODES}" \
    bash -c "[ -d '$TMPDIR' ] || { echo \"Missing TMPDIR=$TMPDIR on \$(hostname)\" >&2; exit 1; }"
if [ $? -ne 0 ]; then
    echo "ERROR: TMPDIR verification failed on one or more nodes" >&2
    exit 1
fi

echo "Successfully created TMPDIR=$TMPDIR on all nodes"
