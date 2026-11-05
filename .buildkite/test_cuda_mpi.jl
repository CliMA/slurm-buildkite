#= Test basic CUDA and CUDA-aware MPI functionality

Main testing functions:

- `test_gpu_visibility`: Test access to at least one GPU and perform a minimal computation
- `test_mpi`: Test a send/receive between arrays on MPI ranks. This is used to
test transfers between CPU-allocated Arrays and GPU-allocated CuArrays.
- `test_exchange_time`: Time repeated halo-sized exchanges between ranks 0 and 1,
reusing the same buffers, and fail if one exchange takes longer than
`MAX_EXCHANGE_US` microseconds (default 500). Exchanges between nodes that
re-register GPU memory on every send take about 2 ms.

For performance, it is important to verify that transfers between CuArrays on different GPUs
are peer-to-peer transfers, which is done by profiling the test with Nsight Systems.

To run this test, you need 2 CUDA devices, CUDA-aware MPI, and Nsight Systems.

First, run the test with two MPI ranks, profiling with Nsight:

    `srun -n 2 nsys profile --trace=nvtx,cuda,mpi --output=report_%q{SLURM_PROCID} julia --project=.buildkite .buildkite/test_cuda_mpi.jl`

If this runs successfully, the test prints MPI and CUDA version info and the following output:

```
Testing GPU Visibility
Basic GPU computation successful
Testing MPI with Array
Transfer successful
Testing MPI with CuArray
Transfer successful
Timing 103824-byte exchanges with Array
...
Timing 103824-byte exchanges with CuArray
...
All tests completed!
```

Once the profile has been generated, analyze the data to determine if a
peer-to-peer transfer occurred between the GPUs:

`nsys stats --report cuda_gpu_trace report_0.nsys-rep | grep -E "memcpy (Peer-to-Peer|PtoP)"`

You should see `[CUDA memcpy Peer-to-Peer]` if the peer-to-peer transfer was successful.
If you don't see this, you can view the full profile analysis using

`nsys stats --report cuda_gpu_trace report_0.nsys-rep`
=#

using CUDA
using MPI
using Test

function root_println(msg... = "")
    rank = MPI.Comm_rank(MPI.COMM_WORLD)
    if rank == 0
        println(msg...)
    end
end

function test_gpu_visibility()
    root_println()
    root_println("Testing GPU Visibility")

    @test CUDA.functional() && CUDA.has_cuda_gpu()
    x = CUDA.ones(1000)
    y = 2 .* x
    result = sum(y) |> Int
    @test result == 2000
    root_println("Basic GPU computation successful")
end

function test_mpi(ArrayType = Array, comm = MPI.COMM_WORLD)
    rank = MPI.Comm_rank(comm)
    MPI.Comm_size(comm) < 2 && error("At least 2 MPI processes required")

    root_println("Testing MPI with ", ArrayType)

    MPI.Barrier(comm)
    N = 1024^2

    if rank == 0
        send_data = ArrayType{Float32}(undef, N); send_data .= 1.0f0
        recv_data = ArrayType{Float32}(undef, N); recv_data .= 0.0f0
        CUDA.synchronize()
        MPI.Send(send_data, 1, 0, comm)
        MPI.Recv!(recv_data, 1, 1, comm)
        @test all(recv_data .== 2.0f0)
        println("Transfer successful")
    elseif rank == 1
        send_data = ArrayType{Float32}(undef, N); send_data .= 2.0f0
        recv_data = ArrayType{Float32}(undef, N); recv_data .= 0.0f0
        CUDA.synchronize()
        MPI.Recv!(recv_data, 0, 0, comm)
        MPI.Send(send_data, 0, 1, comm)
        @test all(recv_data .== 1.0f0)
    end
    CUDA.synchronize()

    MPI.Barrier(comm)
end

function test_exchange_time(
    ArrayType = Array,
    comm = MPI.COMM_WORLD;
    nbytes = 103824,
    nwarmup = 50,
    niters = 1000,
)
    rank = MPI.Comm_rank(comm)
    max_us = parse(Float64, get(ENV, "MAX_EXCHANGE_US", "500"))

    root_println("Timing $nbytes-byte exchanges with ", ArrayType)

    if rank < 2
        other = 1 - rank
        send_data = ArrayType{UInt8}(undef, nbytes); send_data .= rank
        recv_data = ArrayType{UInt8}(undef, nbytes)
        CUDA.synchronize()
        exchange = () -> MPI.Sendrecv!(send_data, recv_data, comm; dest = other, source = other)
        foreach(_ -> exchange(), 1:nwarmup)
    end

    MPI.Barrier(comm)
    if rank < 2
        t0 = MPI.Wtime()
        foreach(_ -> exchange(), 1:niters)
        us = (MPI.Wtime() - t0) / niters * 1e6
        @test all(recv_data .== other)
        if rank == 0
            println("Average exchange time: $(round(us; digits = 1)) us (limit $max_us us)")
            @test us < max_us
        end
    end
    MPI.Barrier(comm)
end

if !MPI.Initialized()
    println("Initializing MPI")
    MPI.Init()
end

rank = MPI.Comm_rank(MPI.COMM_WORLD)
println("MPI Rank: $rank on $(gethostname())")
if rank == 0
    MPI.versioninfo()
    CUDA.versioninfo()
end

test_gpu_visibility()
test_mpi(Array)
test_mpi(CuArray)
test_exchange_time(Array)
test_exchange_time(CuArray)

root_println("All tests completed!")
MPI.Finalize()
