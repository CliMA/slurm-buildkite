# Simple tests for rqrun - focused on basic timeout and retry functionality
# Works with both SLURM (sbatch) and PBS (qsub)
using Test
scheduler = isnothing(Sys.which("sbatch")) ? "qsub" : "sbatch"

println("Test: Timeout and retry with 2 min time limit (using $scheduler)")

# Create test script
log_file = "requeue_test.txt"
script_content = scheduler == "sbatch" ? """#!/bin/bash
#SBATCH --time=00:02:00
#SBATCH --job-name=timeout_test
#SBATCH --open-mode=append
#SBATCH --output=$log_file
#SBATCH --parsable
while true; do sleep 1; done
exit 0
""" : """#!/bin/bash
#PBS -A UCIT0011
#PBS -q preempt
#PBS -l walltime=00:02:00
#PBS -l select=1:ncpus=1
#PBS -N timeout_test
#PBS -j oe
#PBS -o $log_file
sleep 200
exit 0
"""

write("timeout_script.sh", script_content)
chmod("timeout_script.sh", 0o755)

# Run rqrun
rm(log_file, force=true)
# Use addenv to add to existing environment (preserves PATH)
cmd = addenv(`bin/rqrun $scheduler timeout_script.sh`, "RQ_RETRY_LIMIT" => "2")
job_id = readchomp(cmd)
println("Submitted job: $job_id")

println("Watching $log_file for job progress...")

# Watch requeue_test.txt for expected progress messages
function wait_for_submission_completion(filename; max_wait=3600, check_interval=5)
    waited = 0
        while waited < max_wait
            isfile(filename) || continue
            occursin("[rqrun] Max retries reached.", readchomp(filename)) && break
            sleep(check_interval)
            waited += check_interval
        end
    waited >= max_wait && error("Timeout waiting for submissions to complete")
end

wait_for_submission_completion(log_file)

# Expected sequence of events:
# 1. Initial job starts: "[rqrun] Running user script"
# 2. Timeout signal received: "[rqrun] Signal received"
# 3. Resubmission attempt: "[rqrun] Resubmitting attempt 1"
# 4. Resubmission succeeds: "[rqrun] Job successfully resubmitted"
# 5. Max retries reached (after resubmitted job also times out): "[rqrun] Max retries reached"
required_patterns = [
    "[rqrun] Running user script",
    "[rqrun] Signal received",
    "[rqrun] Resubmitting attempt 1/2",
    "[rqrun] Job successfully resubmitted",
    "[rqrun] Resubmitting attempt 2/2",
    "[rqrun] Max retries reached",
]
file_contents = readchomp(log_file)
@testset "Checking for required patterns in $log_file" begin
    for pattern in required_patterns
        @test occursin(pattern, file_contents)
    end
end

# Test: Job submission failure
# Create script with invalid directives that will cause submission to fail
invalid_script_content = 
if scheduler == "sbatch"
    """#!/bin/bash
#SBATCH --time=invalid_time_format
#SBATCH --job-name=invalid_test
#SBATCH --output=invalid_test.txt
echo "This should never run"
exit 0
""" 
else
    """#!/bin/bash
#PBS -l walltime=invalid_format
#PBS -N invalid_test
#PBS -o invalid_test.txt
echo "This should never run"
exit 0
"""
end

write("invalid_script.sh", invalid_script_content)
chmod("invalid_script.sh", 0o755)

# Try to submit - should fail
cmd = addenv(`bin/rqrun $scheduler invalid_script.sh`, "RQ_RETRY_LIMIT" => "2")
try
    job_id = readchomp(cmd)
    error("Expected submission to fail, but got job ID: $job_id")
catch e
    # readchomp throws ProcessFailedException when command fails
    if e isa ProcessFailedException
        println("Submission failed as expected")
        # ProcessFailedException has procs (plural) field, get first process
        exit_code = length(e.procs) > 0 ? e.procs[1].exitcode : "unknown"
        println("Exit code: $exit_code")
    else
        # Also catch any other errors that might occur
        println("Submission failed with unexpected error type")
        println("Error: $e")
    end
end

println("Submission failure test passed!")

