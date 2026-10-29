# Lab 1 — Concurrency in Practice

**Rustem Cimendur, FAF-243** · Verified by Cristofor Fistic, asist. univ.

Count negative, positive, and zero values in 50,000,000 integers using OS threads.
The program uses only the Python standard library.

## Files

| File | Purpose |
| --- | --- |
| [lab.py](lab.py) | Command-line arguments and command dispatch |
| [tasks.py](tasks.py) | Tasks 1a, 1b, 1c, 2, and the lost-update demonstration |
| [dataset.py](dataset.py) | Generate input, split it into parts, and load an integer array |
| [benchmark.py](benchmark.py) | Runtime checks, timing, memory, validation, and the local suite |
| [common.py](common.py) | Counters, JSON output, source fingerprint, and thread error handling |
| [tests/test_lab.py](tests/test_lab.py) | Correctness and command-line tests |
| [PDF report](output/pdf/lab1_report.pdf), [Markdown report](report.md) | Results, explanations, and control questions |
| [output/figures/](output/figures/) | PNG figures used by the report |
| [results/summary.csv](results/summary.csv) | Timing, speed-up, memory, and correctness table |
| [results/measurements.json](results/measurements.json) | All 27 original runs: `local`, `usb`, and `controls` |
| [results/evidence.json](results/evidence.json) | Input manifests, hardware, runtime, USB checks, reconnects, original commands, and test output |

The PDF and recorded measurements are from the original campaign on 22 October
2026. Their `source_sha256` refers to the original `lab.py` at `source_revision`
in `measurements.json`. New runs fingerprint all five runtime modules. Published
measurements are preserved separately from new per-run output files.

## Python and tests

Python **3.13+** is required for `Queue.shutdown()`. CPU scaling measurements
require a **free-threaded** build with the GIL disabled; ordinary Python can run
correctness tests. The recorded campaign used free-threaded CPython 3.14.5.

Run commands from the repository root. With [uv](https://docs.astral.sh/uv/):

```console
uv python install 3.14t
uv run --python 3.14t python lab1/lab.py runtime
uv run --python 3.14t python -m unittest discover -s lab1/tests -v
```

In the examples below, `python` refers to that interpreter. You can also prefix
each command with `uv run --python 3.14t`. Check that `runtime` reports
`free_threaded_build: true` and `gil_enabled: false` before benchmarking.

## Prepare input

```console
python lab1/lab.py generate --count 50000000 --seed 243
python lab1/lab.py split
```

This creates `lab1/data/numbers.txt`, an independent reference-count/SHA-256
manifest, and eight consecutive files in `lab1/data/parts/`. Large input files
are excluded from Git. Generation and splitting refuse to overwrite existing data.

## Local experiments

```console
python lab1/lab.py suite
```

The suite runs each configuration sequentially in a fresh process: tasks 1a and
1c with 1, 2, 4, 8, 16, 32, 64 threads/workers; task 1b with unsafe, locked, and
private counters at the logical processor count, plus one-thread baselines.
Unsafe parallel counting is repeated three times to expose lost updates.
JSON results go to `lab1/results/local/`. To start another campaign, pass
`--output-dir lab1/results/new_local`.

Individual runs (`--threads 32` in 1b should match your logical processor count):

```console
python lab1/lab.py run 1a --threads 8 --require-free-threaded
python lab1/lab.py run 1b --threads 32 --mode unsafe --require-free-threaded
python lab1/lab.py run 1b --threads 32 --mode lock --require-free-threaded
python lab1/lab.py run 1b --threads 32 --mode local --require-free-threaded
python lab1/lab.py run 1c --threads 8 --batch-size 10000 --capacity 100 --require-free-threaded
python lab1/lab.py race-demo
```

Add `--output path/to/result.json` to save an individual run. Timing includes
thread startup, work, joins, and reduction. Task 1b array loading is excluded.
Memory is the process's lifetime peak resident memory. Correct methods must match
all three reference counts; the intentionally unsafe method records failures.
`race-demo` is a separate explanation, excluded from benchmark measurements.

## Task 2: USB storage

1. Copy `part_01.txt` through `part_08.txt` from `lab1/data/parts/` to the USB drive.
   Verify their SHA-256 values against `lab1/data/parts/parts.manifest.json`.
2. Safely eject, physically unplug, and reconnect the drive before **each** run.
   Wait for mounting; do not open or hash the files before timing.
3. Run the following command for 1, 2, and 4 threads, changing `--threads` and
   `--output` each time. Replace the Windows example path with your USB directory.

```console
python lab1/lab.py run 2 --input D:/faf_network_programming/lab1 --threads 1 --require-free-threaded --cold-confirmation "Safely ejected, physically unplugged and reconnected before this run" --output lab1/results/new_usb/task2_01t.json
```

Each worker reads a whole file into one byte buffer, parses it, releases it, and
continues to its next file. The reconnect confirmation records a human action;
the program does not clear the OS cache. The original campaign used an external
USB HDD, as documented in the report.
