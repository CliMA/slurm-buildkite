using Pkg

# This is Pkg.precompile without the try/catch
function precompile_fatal()
    ctx = Pkg.API.Context()
    pkgids = [Base.PkgId(uuid, name) for (name, uuid) in ctx.env.project.deps if !Pkg.API.is_stdlib(uuid)]
    if ctx.env.pkg !== nothing && isfile( joinpath( dirname(ctx.env.project_file), "src", ctx.env.pkg.name * ".jl") )
        push!(pkgids, Base.PkgId(ctx.env.pkg.uuid, ctx.env.pkg.name))
    end

    for pkg in pkgids
        paths = Base.find_all_in_cache_path(pkg)
        sourcepath = Base.locate_package(pkg)
        sourcepath === nothing && continue
        # Heuristic for when precompilation is disabled
        occursin(r"\b__precompile__\(\s*false\s*\)", read(sourcepath, String)) && continue
        stale = true
        for path_to_try in paths::Vector{String}
            staledeps = Base.stale_cachefile(sourcepath, path_to_try)
            staledeps === true && continue
            # TODO: else, this returns a list of packages that may be loaded to make this valid (the topological list)
            stale = false
            break
        end
        if stale
            Base.compilecache(pkg, sourcepath)
        end
    end
    return nothing
end

try
    Pkg.instantiate(;verbose=true)
    precompile_fatal()
catch
    try
        @info "Precompilation faild, trying Pkg.build()"
        Pkg.build(;verbose=true)
        precompile_fatal()
    catch
        @info "Pkg.build() failed, starting from clean depot"
        rm(DEPOT_PATH[1]; recursive=true)
        Pkg.instantiate(;verbose=true)
        precompile_fatal()
    end
end

Pkg.status()
