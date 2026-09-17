#!/bin/bash
#SBATCH --job-name=upload_artifacts_r2
#SBATCH --account=esm
#SBATCH --partition=expansion
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G
#SBATCH --time=24:00:00
#SBATCH --output=upload_artifacts_r2-%j.log

# Mirror CliMA Julia artifacts to the R2 bucket via bin/upload_artifacts_r2.jl.
#
# Usage:
#   # Export R2 credentials first (they are NOT stored in this script):
#   export AWS_ACCESS_KEY_ID=...
#   export AWS_SECRET_ACCESS_KEY=...
#   sbatch bin/upload_artifacts_r2.sbatch [OPTIONS] [ARTIFACT_NAME ...]
#
# Any arguments are forwarded verbatim to the Julia script, e.g.:
#   sbatch bin/upload_artifacts_r2.sbatch --dry-run
#   sbatch bin/upload_artifacts_r2.sbatch --verify mac_lwp
#
# sbatch exports the submitting shell's environment by default, so the
# AWS_* variables set before submission are available inside the job.

set -euo pipefail

# Julia (module) and aws CLI (~/.local/bin) on PATH for the compute node.
module load climacommon
export PATH="$HOME/.local/bin:$PATH"

# pigz uses this for parallel compression.
export JULIA_NUM_THREADS=${SLURM_CPUS_PER_TASK:-8}

# R2 credentials live outside the repo (see ~/.config/clima-r2/env).
source "$HOME/.config/clima-r2/env"


julia "/home/nefrathe/clima/slurm-buildkite/bin/upload_artifacts_r2.jl" "$@"
