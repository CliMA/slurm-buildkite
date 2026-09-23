# Sourced from /etc/profile and /etc/bash.bashrc inside the container so that
# both login (ssh) and non-login interactive shells (docker exec, vscode
# terminal) see the prefetched CliMA artifact depot.

if [ -d /clima-artifacts/artifacts ]; then
    export JULIA_DEPOT_PATH="${JULIA_DEPOT_PATH-${HOME:-/root}/.julia}:/clima-artifacts"
fi

# Friendly status on interactive shells only — quiet otherwise.
case $- in *i*)
    if [ -e /clima-artifacts/.ready ]; then
        echo "[clima-artifacts] ready (mounted in JULIA_DEPOT_PATH)"
    elif [ -d /clima-artifacts ]; then
        echo "[clima-artifacts] still downloading — tail -f /var/log/clima-artifacts.log"
    fi
    ;;
esac
