set -euo pipefail

# RunPod containers have CUDA and Julia pre-installed via the Docker image.
# No module system is available — paths are set directly.

export TMPDIR="${TMPDIR:-/tmp/buildkite-${BUILDKITE_JOB_ID:-runpod}}"
mkdir -p "$TMPDIR"

# Julia is installed via juliaup in the container
export PATH="$HOME/.juliaup/bin:$PATH"

echo "--- RunPod environment"
echo "CUDA version: $(nvcc --version 2>/dev/null | tail -1 || echo 'not found')"
echo "Julia version: $(julia --version 2>/dev/null || echo 'not found')"

if command -v nvidia-smi &> /dev/null; then
    echo "--- GPUs available on RunPod pod"
    nvidia-smi -L
fi
