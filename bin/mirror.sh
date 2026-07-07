#!/usr/bin/env sh

set -x

case "$BUILDKITE_AGENT_META_DATA_QUEUE" in
    "central")
        echo "Mirroring artifacts from central to clima, derecho, and GCP"
        ;;
    *)
        echo "This script only runs on Caltech central"
        exit 0
        ;;
esac

# The Slurm/buildkite job runs in a non-login shell that does not source the
# user profile, so put the Google Cloud SDK on PATH explicitly. (globus is run
# from its own venv via $GLOBUS below, so it does not need to be on PATH.)
PATH="$HOME/google-cloud-sdk/bin:$PATH"
export PATH

# globus-cli lives in a dedicated venv so its dependencies (e.g. urllib3 2.x)
# don't collide with the agent's other Python tooling (e.g. botocore's urllib3
# pin). While logged in as the buildkite user esmbuild, created once with:
#   python3 -m venv ~/globus-venv && ~/globus-venv/bin/pip install globus-cli
GLOBUS="$HOME/globus-venv/bin/globus"

# Mirror the ClimaArtifacts from Caltech Central to our other systems. Each
# destination is reached differently:
#   - Clima:   rsync over ssh (data actually lives on Sampo behind it)
#   - GCP:     rsync over a gcloud-configured ssh alias
#   - Derecho: Globus (NCAR's mandatory MFA rules out non-interactive ssh)
#
# Every destination stores artifacts under a different path, so after copying we
# rewrite the absolute paths in its Overrides.toml from Central's to the local
# ones (see the rewrite step in each mirror_* function).
#
# We deliberately do not `set -e`: a failure mirroring to one destination should
# not prevent us from mirroring to the others.

CENTRAL_SRC="/resnick/groups/esm/ClimaArtifacts/artifacts/"

# Artifacts to skip on every mirror (e.g. the very large CRUJRA forcing data).
# Space-separated directory names under the artifacts root; each consumer below
# expands this into the exclude flags its tool expects.
EXCLUDED_ARTIFACTS="crujra_forcing_data"
RSYNC_ARTIFACT_EXCLUDES=""
GLOBUS_ARTIFACT_EXCLUDES=""
for _artifact in $EXCLUDED_ARTIFACTS; do
    RSYNC_ARTIFACT_EXCLUDES="$RSYNC_ARTIFACT_EXCLUDES --exclude=${_artifact}/"
    GLOBUS_ARTIFACT_EXCLUDES="$GLOBUS_ARTIFACT_EXCLUDES --exclude ${_artifact}"
done

# --- GCP ------------------------------------------------------------------
# Reached by plain rsync/ssh over a gcloud-configured ssh alias, so it reuses
# mirror_ssh (incremental, unlike `gcloud compute scp`). Two one-time setup
# steps, both tied to the `nefrathe@caltech.edu` gcloud account:
#   - cached login: `gcloud auth login` (org policy forbids service-account
#     keys, so we use a user login; refresh token lives in ~/.config/gcloud)
#   - the login node uses OS Login (hence the ext_nefrathe_caltech_edu user), so
#     the ssh key goes in the OS Login profile, not instance metadata:
#       gcloud compute os-login ssh-keys add --key-file ~/.ssh/google_compute_engine.pub
# At run time we refresh the ssh alias with `gcloud compute config-ssh` in case
# the instance's external IP is ephemeral.
GCP_PROJECT="boreal-century-421217"

# --- Derecho --------------------------------------------------------------
# Mirrored via Globus. Both endpoints are mapped collections, so we authenticate
# as the agent user (whose identity maps to a local account on each system)
# rather than a confidential client. Run `globus login` once as the buildkite
# user on central; the CLI caches a refresh token these runs reuse. The
# collection UUIDs (not secret) are Resnick-HPC-Cluster (source) and NCAR
# Campaign Storage (destination). 
# Collection IDs obtained from:
#  - https://ncar-hpc-docs.readthedocs.io/en/latest/storage-systems/data-transfer/globus/
#  - https://www.hpc.caltech.edu/docs/documentation/transferring-files.html#globus
GLOBUS_CENTRAL_COLLECTION="9fc54b35-f66e-4ef0-a36a-49b20d684b99"
GLOBUS_DERECHO_COLLECTION="6b5ab960-7bbf-11e8-9450-0a6d4e044368"

# Bound each Globus task so a stuck transfer (e.g. a permission-denied file it
# keeps retrying) gives up after a few hours instead of running until Globus's
# multi-day default deadline -- which would hang this mirror job. The sync
# comfortably finishes within this window.
GLOBUS_DEADLINE_HOURS=3

# Mirror to an ssh-accessible destination and rewrite its Overrides.toml.
#   $1 = ssh target (user@host)
#   $2 = remote artifact path (with trailing slash)
mirror_ssh() {
    ssh_target="$1"
    remote_path="$2"

    # --omit-dir-times as in https://stackoverflow.com/a/668049
    # --no-perms: don't sync mode bits. Artifact dirs are owned by various users
    #   on the destination; without this, rsync tries (and fails with exit 23) to
    #   chmod dirs it doesn't own. We mirror data, not permissions.
    # --exclude=".[!.]*" is to exclude dotfiles (e.g., NFS temporary files)
    # $RSYNC_ARTIFACT_EXCLUDES skips the artifacts in $EXCLUDED_ARTIFACTS
    # shellcheck disable=SC2086 # intentional word-splitting of the exclude flags
    rsync -av --no-perms --omit-dir-times --exclude=".[!.]*" --exclude="*~" $RSYNC_ARTIFACT_EXCLUDES "$CENTRAL_SRC" "${ssh_target}:${remote_path}"
    rc=$?

    # Always rewrite Overrides.toml, even on a partial transfer. Skipping it
    # leaves every path in Overrides.toml pointing at Central, which breaks
    # *all* artifacts on the destination -- not just the few that failed to copy.
    ssh "$ssh_target" "sed -i 's|${CENTRAL_SRC}|${remote_path}|g' ${remote_path}Overrides.toml" || rc=1

    return "$rc"
}

# Mirror to a Globus destination and rewrite its Overrides.toml.
#   $1 = source collection UUID, $2 = source path (with trailing slash)
#   $3 = destination collection UUID, $4 = destination path (with trailing slash)
mirror_globus() {
    src="$1"
    src_path="$2"
    dst="$3"
    dst_path="$4"

    rc=0

    # Absolute deadline applied to both transfers below, with a wait timeout set
    # just past it so `globus task wait` observes the task's terminal state
    # rather than timing out first (which would leave a live task that 409s the
    # next run).
    # globus-cli accepts '%Y-%m-%dT%H:%M:%S' (no timezone suffix) and treats it
    # as UTC, which is why we generate it with `date -u`.
    deadline=$(date -u -d "+${GLOBUS_DEADLINE_HOURS} hours" '+%Y-%m-%dT%H:%M:%S')
    wait_timeout=$(( GLOBUS_DEADLINE_HOURS * 3600 + 900 ))

    # Mirror the tree. --sync-level mtime transfers only changed files; the
    # excludes mirror the rsync ones above ($EXCLUDED_ARTIFACTS plus dotfiles).
    # We also exclude Overrides.toml -- we ship a path-rewritten copy separately
    # below, so excluding it here keeps the tree from clobbering that rewrite.
    # Record failure but do not bail: we must still rewrite Overrides (see below).
    # shellcheck disable=SC2086 # intentional word-splitting of the exclude flags
    tree_task=$("$GLOBUS" transfer "${src}:${src_path}" "${dst}:${dst_path}" \
        --recursive --sync-level mtime --preserve-mtime \
        $GLOBUS_ARTIFACT_EXCLUDES --exclude '.*' --exclude 'Overrides.toml' \
        --deadline "$deadline" \
        --notify off \
        --label 'ClimaArtifacts mirror' \
        --format unix --jmespath 'task_id')
    if [ -n "$tree_task" ]; then
        echo "Globus tree transfer: https://app.globus.org/activity/${tree_task}"
        "$GLOBUS" task wait --timeout "$wait_timeout" --polling-interval 60 "$tree_task" || rc=1
    else
        rc=1
    fi

    # Always rewrite and ship Overrides.toml, even if the tree transfer failed:
    # skipping it leaves every path pointing at Central, which breaks *all*
    # artifacts on the destination -- not just the ones that failed to copy.
    # Globus cannot run a remote sed, so we stage the rewrite as a dotfile inside
    # the source collection (excluded from the tree above) and transfer it.
    staged="${src_path}.Overrides.tmp"
    sed "s|${CENTRAL_SRC}|${dst_path}|g" "${src_path}Overrides.toml" > "$staged"
    over_task=$("$GLOBUS" transfer "${src}:${staged}" "${dst}:${dst_path}Overrides.toml" \
        --deadline "$deadline" \
        --notify off \
        --label 'ClimaArtifacts Overrides' \
        --format unix --jmespath 'task_id')
    if [ -n "$over_task" ]; then
        echo "Globus Overrides transfer: https://app.globus.org/activity/${over_task}"
        "$GLOBUS" task wait --timeout "$wait_timeout" --polling-interval 60 "$over_task" || rc=1
    else
        rc=1
    fi
    rm -f "$staged"
    return "$rc"
}

# Refresh the ssh host aliases/IPs for the GCP instances so the GCP leg can
# rsync directly over ssh (the login node's external IP may be ephemeral).
gcloud compute config-ssh --project "$GCP_PROJECT" >/dev/null

# The destinations are independent, so mirror them in parallel: the Globus leg
# blocks on `globus task wait`, and we don't want that holding up Clima or GCP.
# Each leg logs to its own file so the concurrent output stays readable, we
# print the logs and a per-destination status summary once all have finished.
log_dir=$(mktemp -d)

# Clima (data actually lives on Sampo)
mirror_ssh "buildkite@clima.gps.caltech.edu" "/net/sampo/data1/ClimaArtifacts/artifacts/" \
    > "${log_dir}/clima.log" 2>&1 &
clima_pid=$!

# GCP (rsync over the gcloud-configured ssh alias; incremental like Clima)
mirror_ssh "ext_nefrathe_caltech_edu@hpc12-slurm-login-001.us-central1-a.boreal-century-421217" \
           "/home/ext_nefrathe_caltech_edu/ClimaArtifacts/artifacts/" \
    > "${log_dir}/gcp.log" 2>&1 &
gcp_pid=$!

# Derecho (behind NCAR MFA -> Globus instead of ssh)
mirror_globus "$GLOBUS_CENTRAL_COLLECTION" "$CENTRAL_SRC" \
              "$GLOBUS_DERECHO_COLLECTION" "/glade/campaign/univ/ucit0011/ClimaArtifacts2/artifacts/" \
    > "${log_dir}/derecho.log" 2>&1 &
derecho_pid=$!

# Names of every leg, in the order they're reaped below. The termination
# handler iterates this to report on legs still running when the job is killed.
LEGS="clima derecho gcp"
reported=""   # legs already printed, so on_terminate doesn't double-report them

# Print a leg's captured log inside a Buildkite collapsible group
# (https://buildkite.com/docs/pipelines/managing-log-output). A successful leg
# is collapsed (`---`); a failed one uses `+++` so the UI auto-expands it.
print_leg_log() {
    name="$1"
    rc="$2"
    case " $reported " in *" $name "*) return 0 ;; esac
    reported="$reported $name"
    if [ "$rc" -eq 0 ]; then
        echo "--- mirror ${name} (rc=0)"
    else
        echo "+++ mirror ${name} FAILED (rc=${rc})"
    fi
    cat "${log_dir}/${name}.log"
}

# If the job is terminated before all legs finish -- e.g. a SLURM/Buildkite
# wall-clock timeout sends SIGTERM -- dump whatever the still-running legs have
# logged so far so their output isn't lost, stop them, and exit non-zero.
# Without this, a leg that hasn't been reaped yet produces no report at all.
on_terminate() {
    echo "+++ mirror INTERRUPTED -- job terminated before all legs finished"
    # shellcheck disable=SC2086 # word-splitting the pid list is intended
    kill $clima_pid $derecho_pid $gcp_pid 2>/dev/null
    for name in $LEGS; do
        case " $reported " in *" $name "*) continue ;; esac
        echo "+++ mirror ${name} INCOMPLETE (still running at termination)"
        cat "${log_dir}/${name}.log" 2>/dev/null
    done
    rm -rf "$log_dir"
    exit 1
}
trap on_terminate TERM INT

# Reap each leg and surface its log as soon as it finishes, so a failure shows
# up immediately rather than waiting on the slowest leg. (No `set -e`, so one
# failure won't abort here.)
wait "$clima_pid";   clima_rc=$?;   print_leg_log clima "$clima_rc"
wait "$derecho_pid"; derecho_rc=$?; print_leg_log derecho "$derecho_rc"
wait "$gcp_pid";     gcp_rc=$?;     print_leg_log gcp "$gcp_rc"
trap - TERM INT   # all legs reaped; the termination handler is no longer needed
rm -rf "$log_dir"

echo "Mirror results (0 = success): clima=${clima_rc} derecho=${derecho_rc} gcp=${gcp_rc}"

# Fail the buildkite step if any leg failed (we still ran them all above). The
# bitwise OR is non-zero iff at least one leg returned non-zero.
exit $((clima_rc | derecho_rc | gcp_rc))
