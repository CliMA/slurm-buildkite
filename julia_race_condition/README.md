# Problem with starting multiple Julia process on a cluster at the same time

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

