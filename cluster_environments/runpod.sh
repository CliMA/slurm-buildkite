set -euo pipefail

# Runpod containers have CUDA and Julia pre-installed via the Docker image.
# No module system is available — paths are set directly.

export TMPDIR="${TMPDIR:-/tmp/buildkite-${BUILDKITE_JOB_ID:-runpod}}"
mkdir -p "$TMPDIR"

# Julia is installed via juliaup in the container
export PATH="$HOME/.juliaup/bin:$PATH"

# Append the prefetched-artifacts depot so Julia resolves artifact hashes from
# local disk via its Overrides.toml. Populated by install-clima-artifacts.sh
# at container start; pre-command blocks on /clima-artifacts/.ready first.
if [ -d /clima-artifacts/artifacts ]; then
    export JULIA_DEPOT_PATH="${JULIA_DEPOT_PATH}:/clima-artifacts"
fi

echo "--- Runpod environment"
echo "CUDA version: $(nvcc --version 2>/dev/null | tail -1 || echo 'not found')"
echo "Julia version: $(julia --version 2>/dev/null || echo 'not found')"

if command -v nvidia-smi &> /dev/null; then
    echo "--- GPUs available on Runpod pod"
    nvidia-smi -L
fi
