set -euo pipefail

source /opt/apps/lmod/lmod/init/bash

# Set OpenMPI installation prefix (helps OpenMPI find its components)
export OPAL_PREFIX="/sw/openmpi-5.0.5"
# Add OpenMPI binaries to PATH (mpiexec, mpirun, etc.)
export PATH="/sw/openmpi-5.0.5/bin:$PATH"
# Add OpenMPI shared libraries to library search path
export LD_LIBRARY_PATH="/sw/openmpi-5.0.5/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

# Add CUDA binaries 
export PATH="/usr/local/cuda/bin:$PATH"
# Add Julia binaries
export PATH="/home/ext_nefrathe_caltech_edu/sw/julia/julia-1.11.5/bin:$PATH"
# Nsight
export PATH="/home/ext_nefrathe_caltech_edu/sw/nsight/nsight-2025.3.1/bin:$PATH"
# Enable UCX memory type caching for improved GPU memory handling performance
export UCX_MEMTYPE_CACHE=y

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
