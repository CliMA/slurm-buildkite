#!/usr/bin/env julia

# Mirror CliMA Julia artifacts to the R2 bucket. Reads a depot-side
# Overrides.toml (<git-tree-sha1> = <on-disk-path>), tarballs each path's
# contents, uploads to R2, and writes docker/clima-artifacts.tsv listing
# what's available for the container's prefetch script.
#
# Run from a machine where the override paths are readable (typically central).
# Requires AWS CLI v2 on PATH and R2 credentials in AWS_ACCESS_KEY_ID /
# AWS_SECRET_ACCESS_KEY.

using Pkg
using TOML

const BUCKET     = "clima-artifacts"
const ENDPOINT   = "https://ec0773bbe656bc4aa705c4ab6d4bf190.r2.cloudflarestorage.com"
const PUBLIC_URL = "https://pub-ec9397f23cd04be5bd2313ee271506d7.r2.dev"
const PREFIX     = "artifacts/"
const REGION     = "auto"
const MANIFEST   = abspath(joinpath(@__DIR__, "..", "docker", "clima-artifacts.tsv"))
const OVERRIDES  = "/resnick/groups/esm/ClimaArtifacts/artifacts/Overrides.toml"

# Artifacts to skip — too large or otherwise inappropriate to mirror on R2.
# Match by basename of the override entry's path (= the derived artifact name).
const SKIP_NAMES = Set([
    "crujra_forcing_data",  # 1.6 TB — too big to mirror
    "DYAMOND_summer_initial_conditions",  # unused
    # Unused: not referenced in ClimaAtmos, ClimaCoupler, or
    # ClimaLand@main. See docs/unused_artifacts.md.
    "DYAMOND_SUMMER_ICS_p14deg",                                   # 18G
    "era5_land_forcing_data2021",                                  # 26G
    "era5_monthly_averages_surface_single_level_1979_2024_hourly", # 23G
    "era5_monthly_averages_atmos_single_level_1979_2024_hourly",   # 3.3G
    "bedrock_depth_30arcseconds",                                  # 1.6G — only _60arcseconds is used
    "merra2_AOD",                                                  # 1.5G
    "calipso_cloudsat_lowres",                                     # 783M
    "surface_temperatures",                                        # 403M
    "era5_surface_fluxes_2008_hourly",                             # 256M
    "mac_lwp",                                                     # 173M
    "ilamb_er_nee",                                                # 164M
    "merra2_AOD_lowres",                                           # 162M
    "era5_monthly_averages_atmos_single_level_1979_2024",          # 137M
])

mutable struct Opts
    overrides::String
    dry_run::Bool
    force_upload::Bool
    verify::Bool
    names::Vector{String}
end

function usage_and_exit(rc=0)
    println("""
    Usage: julia upload_artifacts_r2.jl [OPTIONS] [ARTIFACT_NAME ...]

      --overrides PATH    Depot-side Overrides.toml. Default: $OVERRIDES
      --dry-run           Plan only; no archiving, no uploads, no manifest write.
      --force-upload      Re-upload tarballs even if the R2 object exists.
      --verify            Report which Overrides.toml entries are present in R2
                          and whether each path's content tree-hash still matches
                          its declared hash. No uploads, no manifest write.
      ARTIFACT_NAME ...   Restrict to entries whose basename matches.
    """)
    exit(rc)
end

function parse_args(args)
    o = Opts(OVERRIDES, false, false, false, String[])
    i = 1
    while i <= length(args)
        a = args[i]
        if     a == "--overrides";    o.overrides = args[i+=1]
        elseif a == "--dry-run";      o.dry_run = true
        elseif a == "--force-upload"; o.force_upload = true
        elseif a == "--verify";       o.verify = true
        elseif a in ("-h", "--help"); usage_and_exit()
        elseif startswith(a, "--");   error("Unknown flag: $a")
        else push!(o.names, a)
        end
        i += 1
    end
    isfile(o.overrides) || error("Overrides.toml not found: $(o.overrides)")
    return o
end

object_key(name)     = string(PREFIX, name, ".tar.gz")
public_url_for(name) = string(rstrip(PUBLIC_URL, '/'), "/", object_key(name))

function aws_env()
    env = copy(ENV)
    env["AWS_REGION"] = REGION
    env["AWS_DEFAULT_REGION"] = REGION
    get!(env, "AWS_REQUEST_CHECKSUM_CALCULATION", "when_required")
    get!(env, "AWS_RESPONSE_CHECKSUM_VALIDATION", "when_required")
    return env
end

function object_exists(name)
    cmd = `aws s3api head-object --bucket $BUCKET --key $(object_key(name)) --endpoint-url $ENDPOINT`
    return success(pipeline(setenv(cmd, aws_env()); stdout=devnull, stderr=devnull))
end

# Stream `tar | pigz | aws s3 cp -` directly to R2. No intermediate tarball
# on disk → no /tmp pressure (login-node /tmp is often tiny on HPC). Uses
# pigz when available, gzip otherwise. `--owner=0 --group=0` normalizes
# tarball ownership so consumers don't hit chown errors on extract.
function archive_and_upload(srcdir, name)
    isnothing(Sys.which("tar")) && error("system tar not on PATH")
    gz = isnothing(Sys.which("pigz")) ? "gzip" : "pigz"
    key = object_key(name)
    # `du -sb` walks the dir to get uncompressed bytes. Passed as --expected-size
    # so aws cli scales multipart chunks for huge artifacts (without it, the
    # default 8 MB chunks hit S3's 10,000-part limit at ~80 GB).
    expected = try
        parse(Int, split(read(`du -sb $srcdir`, String), '\t')[1])
    catch
        0
    end
    @info "Streaming to R2" object="s3://$BUCKET/$key" size_gb=round(expected/1e9; digits=1)
    args = ["aws", "s3", "cp", "-", "s3://$BUCKET/$key", "--endpoint-url", ENDPOINT]
    expected > 0 && append!(args, ["--expected-size", string(expected)])
    aws_cmd = setenv(Cmd(args), aws_env())
    run(pipeline(
        `tar --owner=0 --group=0 -cf - -C $srcdir .`,
        `$gz -c`,
        aws_cmd,
    ))
end

# Parse Overrides.toml into a Dict{name => (hash, path)}. Skips hash→hash
# redirects and entries whose path isn't a directory on this machine.
function collect_entries(overrides_path)
    by_name = Dict{String,Tuple{String,String}}()
    for (hash, val) in TOML.parsefile(overrides_path)
        val isa AbstractString || continue
        isdir(val) || (@warn "Skipping non-directory entry" hash path=val; continue)
        name = basename(rstrip(val, '/'))
        if name in SKIP_NAMES
            @info "Skipping (in SKIP_NAMES)" name path=val
            continue
        end
        by_name[name] = (hash, val)
    end
    return by_name
end

# Overwrite the manifest with the given (name, hash, url) triples, sorted.
function write_manifest(path, triples)
    mkpath(dirname(abspath(path)))
    open(path, "w") do io
        println(io, "# name\tgit-tree-sha1\turl")
        println(io, "# Auto-generated by bin/upload_artifacts_r2.jl from Overrides.toml")
        for (name, hash, url) in sort(triples)
            println(io, "$name\t$hash\t$url")
        end
    end
end

function verify(entries, names)
    println("name\tin_r2\tcontent_matches_hash")
    n_total = 0; n_missing = 0; n_drifted = 0
    for name in names
        hash, path = entries[name]
        in_r2 = object_exists(name)
        actual = bytes2hex(Pkg.GitTools.tree_hash(path))
        matches = actual == hash
        println("$name\t$(in_r2 ? "yes" : "no")\t$(matches ? "yes" : "no ($actual)")")
        n_total += 1
        in_r2 || (n_missing += 1)
        matches || (n_drifted += 1)
    end
    @info "Verify summary" n_total n_missing_from_r2=n_missing n_content_drifted=n_drifted
end

function require_aws_creds()
    isnothing(Sys.which("aws")) &&
        error("aws CLI not found on PATH. See docs/artifact_bucket_setup.md.")
    for var in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")
        isempty(get(ENV, var, "")) &&
            error("$var is unset. Export your R2 API credentials before running. See docs/artifact_bucket_setup.md.")
    end
end

function main()
    o = parse_args(ARGS)
    require_aws_creds()
    entries = collect_entries(o.overrides)

    names = if isempty(o.names)
        sort!(collect(keys(entries)))
    else
        for n in o.names
            haskey(entries, n) || error("Name '$n' not in $(o.overrides)")
        end
        sort(o.names)
    end

    if o.verify
        verify(entries, names)
        return
    end

    @info "Processing $(length(names)) artifact(s) from $(o.overrides)" dry_run=o.dry_run

    triples = Tuple{String,String,String}[]
    failed = 0
    for name in names
        hash, path = entries[name]
        url = public_url_for(name)
        push!(triples, (name, hash, url))

        if o.dry_run
            @info "[dry-run]" name path hash url already_in_bucket=object_exists(name)
            continue
        end
        if !o.force_upload && object_exists(name)
            @info "Already in bucket; skipping upload" name
            continue
        end

        try
            archive_and_upload(path, name)
            @info "Uploaded" name
        catch e
            @error "Failed" name exception=(e, catch_backtrace())
            failed += 1
            pop!(triples)
        end
    end

    if !o.dry_run
        write_manifest(MANIFEST, triples)
        @info "Wrote manifest" path=MANIFEST entries=length(triples)
    end
    @info "Done" successes=length(triples) failed=failed
end

main()
