#!/bin/bash
source /etc/bashrc

if [[ "$HOSTNAME" != "login1.cm.cluster" ]]; then
    exit 0
fi

export BUILDKITE_PATH="/groups/esm/slurm-buildkite"
export BUILDKITE_QUEUE='new-central'

cd $BUILDKITE_PATH

DATE="$(date +\%Y-\%m-\%d)"
mkdir -p "logs/$DATE"

bin/poll.py &>> "logs/$DATE/cron"
