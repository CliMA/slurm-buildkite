#!/bin/bash
#
# Minimal test for the RunPod + Buildkite integration.
# Run from the slurm-buildkite directory on central.
#
# Usage:
#   export RUNPOD_API_KEY="your-key"
#   export RUNPOD_DOCKER_IMAGE="your-registry/clima-buildkite:latest"
#   ./test_runpod.sh
#
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

pass() { echo -e "${GREEN}PASS${NC}: $1"; }
fail() { echo -e "${RED}FAIL${NC}: $1"; exit 1; }
skip() { echo -e "${YELLOW}SKIP${NC}: $1"; }

echo "=== RunPod Integration Tests ==="
echo ""

# -------------------------------------------------------------------
# 1. Check required environment variables
# -------------------------------------------------------------------
echo "--- Checking environment variables"

[ -n "${RUNPOD_API_KEY:-}" ]      || fail "RUNPOD_API_KEY is not set"
pass "RUNPOD_API_KEY is set"

[ -n "${RUNPOD_DOCKER_IMAGE:-}" ] || fail "RUNPOD_DOCKER_IMAGE is not set"
pass "RUNPOD_DOCKER_IMAGE is set ($RUNPOD_DOCKER_IMAGE)"

echo ""

# -------------------------------------------------------------------
# 2. Test RunPod API connectivity
# -------------------------------------------------------------------
echo "--- Testing RunPod API connectivity"

RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "https://api.runpod.io/graphql" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $RUNPOD_API_KEY" \
    -d '{"query":"query { myself { id } }"}')

HTTP_CODE=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | head -n -1)

if [ "$HTTP_CODE" = "200" ]; then
    pass "RunPod API returned 200"
else
    fail "RunPod API returned HTTP $HTTP_CODE: $BODY"
fi

if echo "$BODY" | python3 -c "import sys,json; d=json.load(sys.stdin); assert 'errors' not in d" 2>/dev/null; then
    pass "RunPod API authenticated successfully"
else
    fail "RunPod API auth error: $BODY"
fi

echo ""

# -------------------------------------------------------------------
# 3. Test Buildkite API connectivity
# -------------------------------------------------------------------
echo "--- Testing Buildkite API connectivity"

BUILDKITE_PATH="${BUILDKITE_PATH:-$(pwd)}"
TOKEN_FILE="$BUILDKITE_PATH/.buildkite_token"

if [ -f "$TOKEN_FILE" ]; then
    BK_TOKEN=$(cat "$TOKEN_FILE" | tr -d '[:space:]')
    BK_RESPONSE=$(curl -s -w "\n%{http_code}" \
        -H "Authorization: Bearer $BK_TOKEN" \
        "https://api.buildkite.com/v2/organizations/clima/pipelines?per_page=1")
    BK_HTTP=$(echo "$BK_RESPONSE" | tail -1)

    if [ "$BK_HTTP" = "200" ]; then
        pass "Buildkite API returned 200"
    else
        fail "Buildkite API returned HTTP $BK_HTTP"
    fi
else
    skip "No .buildkite_token found — skipping Buildkite API test"
fi

echo ""

# -------------------------------------------------------------------
# 4. Test RunPodJobScheduler import
# -------------------------------------------------------------------
echo "--- Testing RunPodJobScheduler Python import"

IMPORT_TEST=$(cd "$BUILDKITE_PATH" && BUILDKITE_QUEUE=runpod python3 -c "
import sys
sys.path.insert(0, 'bin')
from job_schedulers import RunPodJobScheduler, get_job_scheduler
scheduler = get_job_scheduler()
assert isinstance(scheduler, RunPodJobScheduler), f'Expected RunPodJobScheduler, got {type(scheduler)}'
print('ok')
" 2>&1) || true

if [ "$IMPORT_TEST" = "ok" ]; then
    pass "RunPodJobScheduler loads and get_job_scheduler() returns it for queue=runpod"
else
    fail "Python import failed: $IMPORT_TEST"
fi

echo ""

# -------------------------------------------------------------------
# 5. Test Docker image build (optional)
# -------------------------------------------------------------------
echo "--- Testing Docker image build"

DOCKER_DIR="$BUILDKITE_PATH/docker"
if [ -d "$DOCKER_DIR" ] && command -v docker &>/dev/null; then
    if docker build -t clima-buildkite-test "$DOCKER_DIR" --quiet 2>/dev/null; then
        pass "Docker image builds successfully"

        # Verify key binaries exist in the image
        for bin in julia buildkite-agent nvcc; do
            if docker run --rm clima-buildkite-test which "$bin" &>/dev/null; then
                pass "Docker image has $bin"
            else
                fail "Docker image missing $bin"
            fi
        done
    else
        fail "Docker image build failed"
    fi
else
    if [ ! -d "$DOCKER_DIR" ]; then
        skip "No docker/ directory found at $DOCKER_DIR"
    else
        skip "docker not available — skipping image build test"
    fi
fi

echo ""

# -------------------------------------------------------------------
# 6. Test deploying and terminating a pod (dry run)
# -------------------------------------------------------------------
echo "--- Testing pod deploy + terminate (live)"
echo "    This will create a real pod and immediately terminate it."
read -p "    Proceed? [y/N] " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    # Deploy a minimal pod
    DEPLOY_RESPONSE=$(curl -s -X POST "https://api.runpod.io/graphql" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer $RUNPOD_API_KEY" \
        -d "{\"query\":\"mutation { podFindAndDeployOnDemand(input: { name: \\\"buildkite-test\\\", imageName: \\\"$RUNPOD_DOCKER_IMAGE\\\", gpuTypeId: \\\"NVIDIA A100 80GB PCIe\\\", gpuCount: 1, volumeInGb: 0, containerDiskInGb: 20, env: [{key: \\\"TEST\\\", value: \\\"1\\\"}] }) { id name desiredStatus } }\"}")

    POD_ID=$(echo "$DEPLOY_RESPONSE" | python3 -c "
import sys, json
d = json.load(sys.stdin)
if 'errors' in d:
    print('ERROR: ' + str(d['errors']))
    sys.exit(1)
print(d['data']['podFindAndDeployOnDemand']['id'])
" 2>&1) || true

    if [[ "$POD_ID" == ERROR* ]]; then
        fail "Pod deploy failed: $POD_ID"
    fi

    pass "Pod deployed: $POD_ID"

    # Give it a moment then terminate
    sleep 3

    TERM_RESPONSE=$(curl -s -X POST "https://api.runpod.io/graphql" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer $RUNPOD_API_KEY" \
        -d "{\"query\":\"mutation { podTerminate(input: { podId: \\\"$POD_ID\\\" }) }\"}")

    if echo "$TERM_RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); assert 'errors' not in d" 2>/dev/null; then
        pass "Pod terminated: $POD_ID"
    else
        fail "Pod termination failed: $TERM_RESPONSE"
    fi
else
    skip "Skipped live pod test"
fi

echo ""
echo "=== Done ==="
