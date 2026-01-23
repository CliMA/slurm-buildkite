#!/bin/bash

# Load the bash shell script
source /glade/u/apps/derecho/23.09/spack/opt/spack/lmod/8.7.24/gcc/7.5.0/c645/lmod/lmod/init/bash

# Set only the essential variables
export NCAR_DEFAULT_INFOPATH="/usr/local/share/info:/usr/share/info"
export NCAR_DEFAULT_MANPATH="/usr/local/share/man:/usr/share/man"
export NCAR_DEFAULT_PATH="/usr/local/bin:/usr/bin:/sbin:/bin"
export MODULEPATH="/glade/campaign/univ/ucit0011/ClimaModules-Derecho:/glade/u/apps/derecho/modules/environment"
module load ncarenv/24.12

export PATH="/glade/campaign/univ/ucit0011/software/MPIwrapper/2024_05_27/bin/:$PATH"

# PBS sets TMPDIR to /var/tmp/pbs.${PBS_JOBID}.${HOSTNAME}
# Ensure this directory exists and persists (Buildkite needs it for hook wrappers)
# PBS should create it, but ensure it exists in case it doesn't or was cleaned up
# Store the original PBS TMPDIR before we modify it
if [ -n "$TMPDIR" ] && [ ! -d "$TMPDIR" ]; then
    mkdir -p "$TMPDIR"
    # Ensure it persists (PBS might clean it up too early)
    chmod 755 "$TMPDIR" 2>/dev/null || true
fi

export TMPDIR="$TMPDIR/pbs-${PBS_JOBID}"
pbsdsh -- mkdir -p "${TMPDIR}"
