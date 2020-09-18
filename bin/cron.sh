#!/bin/bash
source /etc/bashrc
if [[ "$HOSTNAME" != "login1" ]]; then
    exit 0
fi

export BUILDKITE_PATH="/groups/esm/climaci"

cd $BUILDKITE_PATH

DATE="$(date +\%Y-\%m-\%d)"
mkdir -p "logs/$DATE"

bin/poll.py &>> "logs/$DATE/cron"
