#= Test basic CUDA and CUDA-aware MPI functionality

Main testing functions:

- `test_gpu_visbility`: Test access to at least one GPU and perform a minimal computation
- `test_mpi`: Test a send/receive between arrays on MPI ranks. This is used to
test transfers between CPU-allocated Arrays and GPU-allocated CuArrays.

For performance, is important to verify that transfers between CuArrays on different GPUs 
are peer-to-peer transfers, which is done by profiling the test with Nsight Systems.

To run this test, you need 2 CUDA devices, CUDA-aware MPI, and Nsight Systems.

First, run the test with two MPI ranks, profiling with Nsight:

    `mpirun -n 2 nsys profile --trace=nvtx,cuda,mpi julia --project bin/test_cuda_mpi.jl`

If this runs successfully, the test prints MPI and CUDA version info and the following output:

```
Testing GPU Visibility
Basic GPU computation successful
Testing MPI with Array
Transfer successful
Testing MPI with CuArray
Transfer successful
All tests completed!
```

Once the profile has been generated, analyze the data to determine if a 
peer-to-peer transfer occured between the GPUs:

`nsys stats --report cuda_gpu_trace report1.nsys-rep | grep grep -E "memcpy (Peer-to-Peer|PtoP)"`

You should see `[CUDA memcpy Peer-to-Peer]` if the peer-to-peer transfer was successful.
If you don't see this, you can view the full profile analysis using

`nsys stats --report cuda_gpu_trace report1.nsys-rep`
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
    
    if CUDA.functional() && CUDA.has_cuda_gpu()
        x = CUDA.ones(1000)
        y = 2 .* x
        result = sum(y) |> Int
        @test result == 2000
        root_println("Basic GPU computation successful")
    else
        root_println("No CUDA device detected")
    end
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
        MPI.Send(send_data, 1, 0, comm)
        MPI.Recv!(recv_data, 1, 1, comm)
        @test all(recv_data .== 2.0f0)
        println("Transfer successful")
    elseif rank == 1
        send_data = ArrayType{Float32}(undef, N); send_data .= 2.0f0
        recv_data = ArrayType{Float32}(undef, N); recv_data .= 0.0f0
        MPI.Recv!(recv_data, 0, 0, comm)
        MPI.Send(send_data, 0, 1, comm)
        @test all(recv_data .== 1.0f0)
    else
        MPI.Barrier(comm)
    end
    CUDA.synchronize()

    MPI.Barrier(comm)
end

if !MPI.Initialized()
    println("Initializing MPI")
    MPI.Init()
end

rank = MPI.Comm_rank(MPI.COMM_WORLD)
println("MPI Rank: $rank")
if rank == 0    
    MPI.versioninfo()
    CUDA.versioninfo()
end

test_gpu_visibility()
test_mpi(Array)
test_mpi(CuArray)

root_println("All tests completed!")
MPI.Finalize()
