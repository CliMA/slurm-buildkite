#!/bin/bash
source /etc/bashrc

case "$(hostname)" in
    "login1.cm.cluster"|"login3.cm.cluster")
        export BUILDKITE_PATH="/groups/esm/slurm-buildkite"
        export BUILDKITE_QUEUE='new-central'
        ;;
    "clima.gps.caltech.edu")
        export BUILDKITE_PATH="/clima/slurm-buildkite"
        export BUILDKITE_QUEUE='clima'
        ;;
esac

cd $BUILDKITE_PATH

DATE="$(date +\%Y-\%m-\%d)"
mkdir -p "logs/$DATE"

bin/poll.py &>> "logs/$DATE/cron"
