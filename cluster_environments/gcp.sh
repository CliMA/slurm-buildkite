set -euo pipefail

source /opt/apps/lmod/lmod/init/bash

unset CUDA_ROOT
unset NVHPC_CUDA_HOME
unset CUDA_INC_DIR
unset CPATH
unset NVHPC_ROOT 

# NVHPC and HPC-X paths
export NVHPC=/sw/nvhpc/Linux_x86_64/24.5
export HPCX_PATH=$NVHPC/comm_libs/12.4/hpcx/hpcx-2.19

# CUDA environment
export CUDA_HOME=$NVHPC/cuda/12.4
export CUDA_PATH=$CUDA_HOME
export CUDA_ROOT=$CUDA_HOME

# MPI via MPIwrapper
export MPITRAMPOLINE_LIB="/sw/mpiwrapper/lib/libmpiwrapper.so"
export OPAL_PREFIX=$HPCX_PATH/ompi

# Library paths - CUDA first, then HPC-X
export LD_LIBRARY_PATH="${CUDA_HOME}/lib64:${HPCX_PATH}/ompi/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

# Executable paths
export PATH=/sw/mpiwrapper/bin:$CUDA_HOME/bin:$PATH
export PATH="$NVHPC/profilers/Nsight_Systems/target-linux-x64:$PATH"

# Julia
export PATH="/sw/julia/julia-1.11.5/bin:$PATH"
export JULIA_MPI_HAS_CUDA=true

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
