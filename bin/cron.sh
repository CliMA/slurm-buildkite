#!/bin/bash
source /etc/bashrc

case "$(hostname)" in
    "login3.cm.cluster"|"login4.cm.cluster")
        export BUILDKITE_PATH="/central/groups/esm/slurm-buildkite"
        export BUILDKITE_QUEUE='new-central'
        ;;
    "clima.gps.caltech.edu")
        export BUILDKITE_PATH="/clima/slurm-buildkite"
        export BUILDKITE_QUEUE='clima'
        ;;
    *)
        echo "Invalid hostname found, exiting..."
        exit 1
    ;;
esac

cd $BUILDKITE_PATH

DATE="$(date +\%Y-\%m-\%d)"
mkdir -p "logs/$DATE"

bin/poll.py &>> "logs/$DATE/cron"
