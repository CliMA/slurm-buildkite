#!/bin/bash
source /etc/bashrc

# To manage old and new at the same time, we define different queues and we run this
# script on both login1 and login3
case "$(hostname)" in
    "login3.cm.cluster")
        export BUILDKITE_PATH="/groups/esm/slurm-buildkite"
        export BUILDKITE_QUEUE='new-central'
        ;;
    "clima.gps.caltech.edu")
        export BUILDKITE_PATH="/clima/slurm-buildkite"
        export BUILDKITE_QUEUE='clima'
        ;;
esac

# cd $BUILDKITE_PATH

DATE="$(date +\%Y-\%m-\%d)"
mkdir -p "logs/$DATE"

export DEBUG_SLURM_BUILDKITE=true

bin/poll.py #&>> "logs/$DATE/cron"
