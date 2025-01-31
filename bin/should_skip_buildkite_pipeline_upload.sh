#!/usr/bin/env sh

# Simple script that check if a pipeline should run or not.
# The rules to skip a pipeline (and mark it as passing) are:
# - only .md files are modified
# - only .github/* files are modified

# To be used in the buildkite step as:
#
# agents:
#     queue: new-central
#     slurm_qos: "debug"
#     slurm_time: "00:05:00"

# steps:
#   - label: "Skip CI If we are only modifying md or .github files"
#     key: "skip_ci"
#     command:
#       - should_skip_buildkite_pipeline_upload.sh
#     soft_fail: true

#   - wait:
#     continue_on_failure: true

#   - label: 'Upload pipeline'
#     command: |
#       if [ $$(buildkite-agent step get "outcome" --step "skip_ci") == "passed" ]; then
#         buildkite-agent pipeline upload .buildkite/pipeline.yml
#       fi

git diff origin/main --name-only | grep -v ".md" | grep -v ".github" -c && exit 0 || exit 1
