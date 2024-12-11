#!/bin/bash

PATH="${BUILDKITE_PATH}/bin:$PATH"

# queue is used for the environment hook, error is used for the error hook
TAGS="queue=${BUILDKITE_QUEUE},error=$2"

ls -l "${BUILDKITE_PATH}/bin/buildkite-agent"

"${BUILDKITE_PATH}/bin/buildkite-agent" start \
  --name "$BUILDKITE_QUEUE-$1-%n" \
  --config "${BUILDKITE_PATH}/buildkite-agent.cfg" \
  --acquire-job "$1" \
  --tags "$TAGS"
