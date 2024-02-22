#!/bin/bash
source /etc/bashrc

if [[ "$(hostname)" != "login1.cm.cluster" &&  "$(hostname)" != "login3.cm.cluster" ]]; then
    exit 0
fi

export BUILDKITE_PATH="/groups/esm/slurm-buildkite"
export BUILDKITE_QUEUE='central'

cd $BUILDKITE_PATH

DATE="$(date +\%Y-\%m-\%d)"
mkdir -p "logs/$DATE"

bin/poll.py &>> "logs/$DATE/cron"
