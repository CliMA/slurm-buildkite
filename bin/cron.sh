#!/bin/bash
source /etc/bashrc

export BUILDKITE_PATH="/clima/slurm-buildkite"
export BUILDKITE_QUEUE='clima'

cd $BUILDKITE_PATH

DATE="$(date +\%Y-\%m-\%d)"
mkdir -p "logs/$DATE"

bin/poll.py &>> "logs/$DATE/cron"
