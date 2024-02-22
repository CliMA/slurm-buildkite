#!/bin/bash
source /etc/bashrc

if [[ "$(hostname)" != "login1.cm.cluster" &&  "$(hostname)" != "login3.cm.cluster" ]]; then
    exit 0
fi

export BUILDKITE_PATH="/groups/esm/slurm-buildkite"

# To manage old and new at the same time, we define different queues and we run this
# script on both login1 and login3
if [[ "$(hostname)" == "login1.cm.cluster" ]]; then
    # login1 is our legacy node
    export BUILDKITE_QUEUE='central'
else
    # login3 is our new system
    export BUILDKITE_QUEUE='new-central'
fi

cd $BUILDKITE_PATH

DATE="$(date +\%Y-\%m-\%d)"
mkdir -p "logs/$DATE"

bin/poll.py &>> "logs/$DATE/cron"
