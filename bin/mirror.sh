#!/usr/bin/env sh

set -xe

case "$BUILDKITE_AGENT_META_DATA_QUEUE" in
    "new-central")
        echo "Mirroring artifacts from central to clima"
        ;;
    *)
        echo "This script only runs on Caltech central"
        exit 0
        ;;
esac

# Mirror the artifacts from Central to Clima
#
# This relies on having set up ssh keys
#
# Note, the data does not live on Clima. It lives on Sampo! This mirror is more
# expensive than it has to be because there is an extra NTFS sync involved. We
# could sync the data directly on Sampo, everything is a little more
# straightforward when we use the buildkite user on clima.

CENTRAL_SRC="/groups/esm/ClimaArtifacts/artifacts/"
CLIMA_DEST="/net/sampo/data1/ClimaArtifacts/artifacts/"

CLIMA_OVERRIDES="$CLIMA_DEST""Overrides.toml"

# --omit-dir-times as in https://stackoverflow.com/a/668049
# --exclude=".[!.]*" is to exclude dotfiles (e.g., NFS temporary files)
rsync -av --omit-dir-times --exclude=".[!.]*" --exclude="*~" "$CENTRAL_SRC" "buildkite@clima.gps.caltech.edu:$CLIMA_DEST"

# Second, we have to update the Overrides.toml on Clima
ssh buildkite@clima.gps.caltech.edu "sed -i 's|/groups/esm/ClimaArtifacts/artifacts/|/net/sampo/data1/ClimaArtifacts/artifacts/|g' $CLIMA_OVERRIDES"


