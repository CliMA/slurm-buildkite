#!/bin/bash

# Companion to schedule_job.sh, but for metrics-poll mode: this launches a
# generic Buildkite agent that picks up whatever job comes next on $QUEUE,
# rather than being tied to one job UUID via --acquire-job. $BUILDKITE_PATH is
# passed positionally (see metrics_poll.py) rather than inherited, since some
# Slurm variants don't propagate env vars into batch scripts reliably.
QUEUE="$1"
BUILDKITE_PATH="$2"

PATH="${BUILDKITE_PATH}/bin:$PATH"

"${BUILDKITE_PATH}/bin/buildkite-agent" start \
  --name "$QUEUE-generic-%n" \
  --config "${BUILDKITE_PATH}/buildkite-agent.cfg" \
  --tags "queue=$QUEUE" \
  --disconnect-after-job \
  --disconnect-after-idle-timeout=60
