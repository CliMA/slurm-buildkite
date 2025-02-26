#!/bin/bash
export MODULEPATH="/groups/esm/modules:$MODULEPATH"
module load git/2.39.3-gcc-11.3.1-zfr3sti
set -x
echo "SLURM_NODELIST: $SLURM_NODELIST"

pdsh -w $SLURM_NODELIST mkdir -p "${TMPDIR}" || \
srun --ntasks-per-node=1 --ntasks=${SLURM_JOB_NUM_NODES} mkdir -p "${TMPDIR}"    

# Check if TMPDIR was created
pdsh -w "$SLURM_NODELIST" test -d "${TMPDIR}" || \
srun --ntasks-per-node=1 --ntasks="${SLURM_JOB_NUM_NODES}" test -d "${TMPDIR}" || { \
    echo "Error: Failed to create $TMPDIR"; exit 1; \
}

set +x
