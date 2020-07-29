#!/bin/bash
if [[ "$HOSTNAME" != "login1" ]]; then
    exit 0
fi

source /etc/bashrc

cd /groups/esm/buildkite
bin/poll.py &>> "logs/cron-$(date +\%Y-\%m-\%d)"
