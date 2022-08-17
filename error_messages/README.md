# Error messages (CI and beyond)

## ERROR: LoadError: SystemError: No such file or directory (Julia depot path error)

Errors like

```
ERROR: The following 9 direct dependencies failed to precompile:

Combinatorics [861a8166-3701-5b0c-9a16-15d98fcdc6aa]

Failed to precompile Combinatorics [861a8166-3701-5b0c-9a16-15d98fcdc6aa] to /central/scratch/esm/slurm-buildkite/calibrateedmf-ci/depot/cpu/compiled/v1.7/Combinatorics/jl_Gv23Ay.
ERROR: LoadError: SystemError: opening file "/central/scratch/esm/slurm-buildkite/calibrateedmf-ci/depot/cpu/packages/Combinatorics/Udg6X/src/numbers.jl": No such file or directory
```

are due to upstream issues in Julia. The issue is a race condition that we experience when running multiple processes. For more information, please see the issue ([#31953](https://github.com/JuliaLang/julia/issues/31953)).

The source of the race conditions can happen in multiple ways. And the issue is more common when using the `JULIA_DEPOT_PATH`, which is specified in our `.buildkite/pipeline.yml` files.

We "accept" using this flakey test configuration because it speeds up initialization from ~10-15 min per build to ~1 min per build. We could abandon using the Julia depot path, but then our continuous integration test times, and the time until the tests start, will take 10-15 min longer. So using the Julia depot path has upsides and downsides.

Sometimes this race condition can lead to a corrupted depot path, in which case we need to clear (delete) the depot path on Caltech Central in order to un-break CI. These issues are per-repo, and we have a few buildkite pipelines dedicated to making this easy (for those repos using the Julia depot path).

If you want to opt-out of using the Julia depot path, then simply delete the environment variable in the buildkite yaml file, which looks like this:

```
  JULIA_DEPOT_PATH: "${BUILDKITE_BUILD_PATH}/${BUILDKITE_PIPELINE_SLUG}/depot/cpu"
```

## perl: error: get_addr_info: getaddrinfo()

TODO: document

```
perl: error: get_addr_info: getaddrinfo() failed: Name or service not known
perl: error: slurm_set_addr: Unable to resolve "head1"
perl: error: slurm_get_port: Address family '0' not supported
perl: error: Error connecting, bad data: family = 0, port = 0
perl: error: slurm_persist_conn_open_without_init: failed to open persistent connection to host:head1:6819: No such file or directory
perl: error: Sending PersistInit msg: No such file or directory
perl: error: get_addr_info: getaddrinfo() failed: Name or service not known
perl: error: slurm_set_addr: Unable to resolve "head1"
perl: error: Unable to establish control machine address
Use of uninitialized value in subroutine entry at /central/slurm/install/current/bin/seff line 57, <DATA> line 602.
perl: error: get_addr_info: getaddrinfo() failed: Name or service not known
perl: error: slurm_set_addr: Unable to resolve "head1"
perl: error: slurm_get_port: Address family '0' not supported
perl: error: Error connecting, bad data: family = 0, port = 0
perl: error: Sending PersistInit msg: No such file or directory
perl: error: DBD_GET_JOBS_COND failure: Unspecified error
```

## 🚨 Error: The command exited with status 137

This error is indicative of insufficient memory for a job. One way to fix this is to request more memory for the job:

```
      - label: "held suarez (ρθ)"
        command: "julia --project=examples examples/driver.jl"
        artifact_paths: "held_suarez/*"
        agents:           # need to add this
          slurm_mem: 20GB # need to add this (with appropriate memory request)
```

See https://www.hpc.caltech.edu/documentation/slurm-commands for more details on slurm flags.

## 🚨 Error: The global post-command hook exited with status 2

TODO: document

## ERROR: LoadError: importing ___ into Main conflicts with an existing identifier

Older versions of julia did not support importing packages with the syntax

```julia
import OrdinaryDiffEq as ODE
```

One way around this was to define a constant

```julia
import OrdinaryDiffEq
const ODE = OrdinaryDiffEq
```

However, these two ways of importing are in conflict with one another, and trying them both together, in the same scope, results in the error `ERROR: LoadError: importing ODE into Main conflicts with an existing identifier`.

