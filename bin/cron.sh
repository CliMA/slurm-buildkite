#!/bin/bash

case "$(hostname)" in
    "login3.cm.cluster")
        export BUILDKITE_PATH="/central/groups/esm/slurm-buildkite"
        export BUILDKITE_QUEUE='new-central'
        ;;
    "clima.gps.caltech.edu")
        export BUILDKITE_PATH="/clima/slurm-buildkite"
        export BUILDKITE_QUEUE='clima'
        ;;
    # TODO: Figure out a way to avoid collisions with hostnames like "cron"
    # `hostname -f` on Derecho does not help
    derecho[0-7]|"cron")
        export BUILDKITE_PATH="/glade/campaign/univ/ucit0011/slurm-buildkite"
        export BUILDKITE_QUEUE='derecho'
        ;;
    "hpc12-slurm-login-001")
        export BUILDKITE_PATH="/home/ext_nefrathe_caltech_edu/slurm-buildkite"
        export BUILDKITE_QUEUE='gcp'
        # We need to alter PATH for access to slurm binaries in `bin/poll.py`
        export PATH=/usr/local/bin:$PATH
        ;;
    *)
        echo "Invalid hostname found, exiting..."
        exit 1
        ;;
esac

if [[ ! -d "$BUILDKITE_PATH" ]]; then
    echo "Could not find buildkite dir $BUILDKITE_PATH. Exiting..."
    exit 1
fi

bashrc_locations=(
    "/etc/bashrc"
    "/etc/bash.bashrc"
    "$HOME/.bashrc"
    "/usr/local/etc/bashrc"
)

for bashrc in "${bashrc_locations[@]}"; do
    if [ -f "$bashrc" ]; then
        source "$bashrc"
        break
    fi
done

cd $BUILDKITE_PATH

DATE="$(date +\%Y-\%m-\%d)"
mkdir -p "logs/$DATE"

bin/poll.py &>> "logs/$DATE/cron"
