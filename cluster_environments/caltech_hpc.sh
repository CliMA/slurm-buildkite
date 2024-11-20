#!/bin/bash
export MODULEPATH="/groups/esm/modules:$MODULEPATH"
module load git/2.39.3-gcc-11.3.1-zfr3sti

echo "SLURM_NODELIST: $SLURM_NODELIST"

if ! pdsh -w $SLURM_NODELIST mkdir -p "${TMPDIR}"; then
    echo "Warning: pdsh failed to create directory. Falling back to srun."
    srun --ntasks-per-node=1 --ntasks=${SLURM_JOB_NUM_NODES} mkdir -p "${TMPDIR}"
fi

# Check if TMPDIR was created
if ! srun --ntasks-per-node=1 --ntasks=${SLURM_JOB_NUM_NODES} test -d "${TMPDIR}"; then
    echo "Error: Failed to create $TMPDIR"
    exit 1
fi
