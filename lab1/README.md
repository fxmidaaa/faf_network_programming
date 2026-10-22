# Lab 1 - Concurrency in Practice

- **Author:** Rustem Cimendur
- **Group:** FAF-243
- **Verified:** Cristofor Fistic, asist. univ.

This laboratory measures OS threads on 50,000,000 integers. All counting code is
Python and uses the standard library. There is no multiprocessing, NumPy counting,
or simulated workload. The published measurements use **CPython 3.14.5,
free-threaded build, GIL disabled**.

## Deliverables

- [PDF report](output/pdf/lab1_report.pdf): hardware, methods, charts, measured
  results, explanations, all control questions, and limitations.
- [Editable report](report.md) and [defense guide](DEFENSE.md).
- [Counting program](lab.py), [correctness tests](tests/test_lab.py), and
  [report/figure generator](build_report.py).
- [Recorded results and evidence](results/): JSON measurements, original command
  output, dataset/checksum manifests, hardware, and USB copy verification.
- [Illustrations and charts](output/figures/).

The large input is kept locally in `lab1/data/`, outside Git. Its seed and SHA-256
are recorded so that it can be regenerated and verified.

## Set up Python

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then run the
following commands **from the repository root**:

```console
uv python install 3.14t
uv run --python 3.14t python lab1/lab.py runtime
uv run --python 3.14t python -m unittest discover -s lab1/tests -v
```

The runtime output must contain `"free_threaded_build": true` and
`"gil_enabled": false`. A regular recent Python installation is not automatically
free-threaded. `--require-free-threaded` rejects an unsuitable interpreter.

The core program needs **Python 3.13 or newer** because it uses `Queue.shutdown`.
Ordinary GIL-enabled Python can run correctness tests, but its CPU-scaling results
are not interchangeable with the published free-threaded measurements.

## Generate and split the full input

```console
uv run --python 3.14t python lab1/lab.py generate --count 50000000 --seed 243
uv run --python 3.14t python lab1/lab.py split
```

The first command creates `numbers.txt` with one integer per line, in
[-1,000,000, 1,000,000], and an independent sign-count manifest. It refuses to
overwrite an existing input. The second command produces eight consecutive files
of 6,250,000 lines and checks that their concatenated SHA-256 equals the source.
The generated full file is 369,449,238 bytes for the recorded seed and runtime.

## Run all local measurements

```console
uv run --python 3.14t python lab1/lab.py suite
```

The suite starts a **fresh process for every configuration**, sequentially:

| Task | Configurations |
| --- | --- |
| 1a | 1, 2, 4, 8, 16, 32, 64 independent file-reading threads |
| 1c | 1, 2, 4, 8, 16, 32, 64 consumers, plus one producer |
| 1b | Three unsafe runs; one locked and one per-thread run, using the logical processor count |
| 1b extra baselines | One thread for each counting method, to define method-specific speed-up |

Do not run other benchmarks at the same time. Keep the power supply and power
plan stable. Each result is saved before the next configuration starts. Rerunning
the suite resumes matching source-version results. For a new measurement campaign,
use `--output-dir lab1/results/new_local`; do not mix code versions in one directory.

Individual examples:

```console
uv run --python 3.14t python lab1/lab.py run 1a --threads 8 --require-free-threaded --output lab1/results/example_1a.json
uv run --python 3.14t python lab1/lab.py run 1b --threads 32 --mode unsafe --require-free-threaded
uv run --python 3.14t python lab1/lab.py run 1b --threads 32 --mode lock --require-free-threaded
uv run --python 3.14t python lab1/lab.py run 1b --threads 32 --mode local --require-free-threaded
uv run --python 3.14t python lab1/lab.py run 1c --threads 8 --batch-size 10000 --capacity 100 --require-free-threaded
uv run --python 3.14t python lab1/lab.py race-demo
```

For Task 1b, replace 32 with your own logical processor count. The preload into a
32-bit integer array is excluded from timing and reported separately. No artificial
sleep or barrier is inserted in the unsafe benchmark. `race-demo` is a separate,
controlled two-thread explanation and is never used as a timing result.

## Task 2 - physical USB storage

1. Copy `part_01.txt` through `part_08.txt` from `lab1/data/parts/` into a dedicated
   directory on the USB drive. The recorded directory is
   `D:/faf_network_programming/lab1`. Check the copied hashes against
   `results/parts.manifest.json` **before** the cold-cache procedure.
2. Close anything using that directory. Safely eject the drive, physically unplug
   it, and reconnect it. Wait until Windows mounts it. Do not open, preview, scan,
   or hash the text files after reconnecting and before the measurement.
3. Run exactly one configuration:

```console
uv run --python 3.14t python lab1/lab.py run 2 --input D:/faf_network_programming/lab1 --threads 1 --require-free-threaded --cold-confirmation "Safely ejected, physically unplugged and reconnected before this run" --output lab1/results/usb/task2_01t.json
```

4. Repeat the **entire eject/unplug/reconnect procedure** before the 2-thread run
   and again before the 4-thread run, changing `--threads` and the output filename.

The confirmation is a human record, not a software claim that a physical action
has occurred. Simply closing and reopening a file does not clear the filesystem
cache. A USB HDD is used instead of a flash stick with the student's confirmation
that this substitution is acceptable; the report identifies the actual device.

For automatic recording of all three reconnects and measurements, use the supplied
Windows observer instead of launching the three configurations manually:

```console
uv run --python 3.14t python lab1/usb_campaign.py --input D:/faf_network_programming/lab1
```

Follow its action message for each reconnect. It checks only drive-letter presence,
records absence and reappearance, waits two seconds for mounting, then starts one
measurement. It never opens the input files before timing. The published outputs
already exist, so use `--output-dir lab1/results/new_usb` for a new campaign.
The report uses `results/usb/reconnect_*.json` as corroborating OS evidence.

Each worker reads a complete file with one `read()` call into one byte buffer,
then parses it without making a list of lines. Eight files are assigned 8/4/2 per
worker for 1/2/4 threads. Per-file read and parse times are also recorded.

## Measurement and correctness conventions

- Time: `time.perf_counter()`, including thread start, work, joining, and reduction.
  Generation, splitting, Task 1b preload, result serialization, and plotting are
  excluded. CPU time is `time.process_time()` over the same measured interval.
- Memory: Windows `GetProcessMemoryInfo().PeakWorkingSetSize`, in MiB. This is the
  whole process's lifetime peak resident working set, including the interpreter
  and preloaded array; it is not an allocation-only or incremental-memory metric.
- Speed-up: `T(1) / T(p)` within the same task/method; 1c uses consumer count on
  its horizontal axis and has one extra producer thread. Unsafe speed-up is shown
  only as a diagnostic because its incorrect result is not useful completed work.
- Every result includes all three counters, their sum, expected totals, runtime
  GIL state, dataset hash, and counting-source hash. Correct methods fail if totals
  differ. The deliberately unsafe method records incorrect totals without hiding
  the failure.
- Required configurations have one timing observation each, except the three
  unsafe runs. No error bars or significance claims are inferred from single runs.
- Local file runs use the normal OS cache. USB required runs follow the physical
  reconnect protocol. Additional storage controls, if present, are labeled and
  excluded from the required USB curves.

### Additional matched-parser storage controls

After completing the three cold runs, the report also measures the same buffer
parser once on the local parts and once on the now-warm USB files. These controls
help separate parser overhead from storage cost; neither replaces a cold run.

```console
uv run --python 3.14t python lab1/lab.py run 2 --input lab1/data/parts --threads 1 --role additional_storage_control --cold-confirmation "Diagnostic NVMe control; normal OS cache; not a cold USB run" --require-free-threaded --output lab1/results/controls/nvme_01t.json
uv run --python 3.14t python lab1/lab.py run 2 --input D:/faf_network_programming/lab1 --threads 1 --role additional_warm_control --cold-confirmation "Diagnostic warm USB control after the cold campaign; no reconnect" --require-free-threaded --output lab1/results/controls/warm_usb_01t.json
```

## Rebuild the report

The report tools are separate from the benchmark runtime so plotting libraries
cannot silently change its GIL state or measured memory.

```console
uv run --python 3.13 --with-requirements lab1/requirements-report.txt python lab1/build_report.py
```

This reads recorded JSON files and regenerates the PDF, editable Markdown, CSV
summary, charts, and evidence illustrations. It does not rerun any experiment.
The report builder requires the complete local and three cold USB result sets.

## Code map

| Function in `lab.py` | Responsibility |
| --- | --- |
| `generate`, `split_input` | Bounded-memory input preparation and SHA-256 manifests |
| `count_file_range`, `task1a` | Independent byte partitions aligned to complete lines |
| `load_array`, `task1b` | Untimed integer-array preload and three synchronization strategies |
| `task1c` | Bounded blocking queue, one reader, and graceful queue shutdown |
| `count_buffer`, `task2` | One-buffer file reads and streaming parsing inside each buffer |
| `benchmark`, `peak_memory_bytes` | Timing, CPU/memory measurement, validation, and evidence |
| `suite` | Sequential fresh-process measurement campaign |

`inspect_usb.py` performs read-only Windows USB-hub descriptor queries. Its recorded
result confirms device descriptor USB 3.10 and SuperSpeed operation; the exact
physical link rate is not inferred from the host-controller marketing name.
