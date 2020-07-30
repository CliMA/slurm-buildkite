#!/bin/bash
if [[ "$HOSTNAME" != "login1" ]]; then
    exit 0
fi

source /etc/bashrc

cd /groups/esm/buildkite
DATE="$(date +\%Y-\%m-\%d)"
mkdir -p "logs/$DATE"
bin/poll.py &>> "logs/$DATE/cron"
