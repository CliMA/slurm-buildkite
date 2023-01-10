using MPI

MPI.Init()

sleep(10)

MPI.Barrier(MPI.COMM_WORLD)

sleep(10)

rank = MPI.Comm_rank(MPI.COMM_WORLD)
maxrank = MPI.Allreduce(rank, max, MPI.COMM_WORLD)

MPI.Finalize()
