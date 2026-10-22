# Defense guide

## Explain the program in two minutes

The dataset has 50 million signed integers. A generation-time manifest records
the reference negative, positive, and zero totals. Every correct configuration
must reproduce those three totals, not only their sum.

Task 1a gives each OS thread a byte interval in the original file. The thread
aligns its own starting position and counts complete lines beginning before its
interval ends. It keeps local counters, so the hot loop has no shared counter.

Task 1b loads a compact integer array before the timer starts. The same logical
processor count and the same array are used for three methods: unsynchronized
shared counters, one lock per increment, and private counters merged after joins.
Array views avoid copying the input for each thread.

Task 1c uses one producer and a bounded queue of at most 100 batches, each with
10,000 raw lines. Workers parse and count. `Queue.shutdown()` lets queued work
drain and wakes consumers when no more work is possible. A worker error forces
shutdown and is propagated instead of producing a plausible partial total.

Task 2 assigns whole files evenly. Each thread reads one file into one byte
buffer, parses it without a list of lines, releases it, and proceeds to its next
file. The drive is physically reconnected before every required configuration.

## Control questions

1. **Physical core versus logical processor.** A physical core is a hardware
   execution core. A logical processor is a scheduling context exposed to the OS;
   simultaneous multithreading lets some cores expose more than one context.
   This i9-13900HX has 24 physical cores and 32 logical processors, so the contexts
   do not represent 32 equally powerful independent cores. Read the measured
   optimum from the report; neither 24 nor 32 guarantees the fastest result.

2. **Partition boundaries.** For a nonzero byte start, read byte `start - 1`.
   If it is LF, the current position already starts a line. Otherwise skip the
   remainder of that partial line. Count only lines starting before `end`.
   A line crossing `end` belongs to the earlier interval; the next worker skips
   its remainder. Tests try every two-way cut position and more threads than lines.

3. **Lost updates.** Thread A reads counter = 0. Thread B also reads 0. A computes
   and writes 1. B computes and writes 1. Two values were processed but the counter
   advanced once. A container's internal safety does not make the entire
   read/add/write sequence atomic. The separate barrier demonstration forces this
   schedule; the large unsafe benchmarks use natural scheduling.

4. **Why private counters are faster.** Each worker updates its own integers;
   only a small reduction happens after joining. A shared lock serializes every
   increment, adds lock acquisition overhead, and transfers ownership between
   cores. Increasing the number of threads can increase contention rather than
   throughput.

5. **I/O-bound USB versus network.** I/O-bound means the critical path is dominated
   by waiting for external data rather than executing the counting/parsing code.
   Multiple readers of one HDD still share one mechanism, controller, and link;
   competing streams can cause seeks. Independent network requests can overlap
   waiting on different remote operations. Concurrency helps when independent
   waiting exists and capacity is available, not merely because an API performs
   I/O. Use measured one-thread read/parse fractions and storage controls to decide
   whether this Python workload is actually I/O-bound.

6. **Static partitioning versus a work queue.** Static partitioning avoids a
   central queue and is effective for predictable, uniform work. A queue balances
   uneven task durations dynamically and overlaps reading with counting, but adds
   communication, synchronization, and a possible producer bottleneck. A bounded
   queue applies backpressure and limits queued input memory.

## Likely follow-up questions

- **Why free-threaded Python?** Traditional CPython has a GIL that prevents
  simultaneous execution of pure Python bytecode by multiple threads. This work
  uses a separate free-threaded build and records that the GIL is disabled. I/O
  can overlap even in ordinary CPython, but that does not establish CPU parallelism.
- **Why not use processes?** The assignment studies OS threads and synchronization
  inside one process. Processes would change both sharing and memory accounting.
- **Why check individual totals?** A duplicated negative and a skipped positive
  can leave the grand total unchanged. All three reference totals must match.
- **Why fresh processes?** Windows reports a lifetime memory high-water mark;
  reusing a process would retain earlier peaks and allocator state.
- **Why is an incorrect unsafe run sometimes fast?** It loses updates and does
  less useful accounting. A short duration does not make it a valid solution.
- **One-line batches?** Many more queue operations, lock transitions, allocations,
  and wake-ups per counted number; communication can dominate useful work.
- **An unbounded queue?** A fast producer can retain most of the file as Python
  line objects, increasing peak memory and possibly causing paging.
- **Can a single observation establish a small difference?** No. It demonstrates
  the recorded behavior, but repeated trials are needed to estimate variability.
