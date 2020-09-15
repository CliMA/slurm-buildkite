#!/bin/bash
source /etc/bashrc
if [[ "$HOSTNAME" != "login1" ]]; then
    exit 0
fi

cd /groups/esm/climaci

DATE="$(date +\%Y-\%m-\%d)"
mkdir -p "logs/$DATE"

bin/poll.py &>> "logs/$DATE/cron"
