using HTTP, JSON, Plots, Dates, DataFrames

token_path = joinpath(@__DIR__, "..", ".buildkite_token")
buildkite_api_token = readchomp(token_path)
buildkite_endpoint = "https://api.buildkite.com/v2/organizations/clima/pipelines/climacore-ci/builds"


resp = HTTP.get(
    buildkite_endpoint,
    Dict("Authorization" => "Bearer $buildkite_api_token",
        );
    params = Dict(
        "page" => 1,
        "per_page" => 100,
        "state[]" => ["scheduled", "running", "failing"],
        # "created_from" => since
    )
)

json_body = JSON.Parser.parse(String(resp.body))

build = json_body[1]
job = build["jobs"][1]
job["type"]
job["step_key"]


function extract_jobs(json_body)
    data = DataFrame("build_number" => Int[], "step_key" => String[], "jobid" => Int[], "state" => String[])
    for build in json_body
        build_number = build["number"]    
        for job in build["jobs"]
            if job["type"] != "script"
                continue
            end
            step_key = job["step_key"]
            if isnothing(step_key)
                continue
            end
            state = job["state"]
            agent = job["agent"]
            if isnothing(agent)
                continue
            end
            agent_meta_data = agent["meta_data"]
            jobid = nothing
            for item in agent_meta_data
                key,value = split(item,"=", limit=2)
                if key == "jobid"
                    jobid = parse(Int, value)
                    break
                end
            end
            if isnothing(jobid)
                continue
            end
            push!(data, (;build_number, step_key, jobid, state))
        end
    end
    return data
end
extract_jobs(json_body)



builds = []
npages = 2
for n in 1:npages
    resp = HTTP.get(
        buildkite_endpoint,
        Dict("Authorization" => "Bearer " * buildkite_api_token,
            );
        #params/query don't work
        params=Dict("page" => n,
            "per_page" => 100,
            "state[]" => ["scheduled", "running", "failing"])
        # "created_from" => since
        )
    push!(builds, resp)
end

# Parse JSON for timing data
df = DateFormat("y-m-dTH:M:S.sZ")
datetimes = DateTime[]
timings = Float64[]
urls = []
Links = []
for page in builds
    json_body = JSON.Parser.parse(String(page.body))
    push!(Links,page.headers[19][2])
    for row in json_body
        if haskey(row, "started_at") && haskey(row, "finished_at") && row["state"] != "canceled"
            if !(isnothing(row["started_at"]) || isnothing(row["finished_at"])) 
                start_time = DateTime(row["started_at"], df)
                end_time = DateTime(row["finished_at"], df)
                push!(urls, row["url"])
                push!(datetimes, start_time)
                push!(timings, (end_time - start_time).value/1000/60)
            end
        end
    end
end

plot(datetimes, timings, seriestype=:scatter, ylabel="Duration (Minutes)", xlabel="Date")
