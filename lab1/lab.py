"""Concurrency in Practice: one command-line program for every experiment.

The counting code uses only the Python standard library and actual OS threads.
Use a free-threaded CPython 3.14 build for the published benchmarks.
"""

from __future__ import annotations

import argparse
from array import array
import ctypes
from ctypes import wintypes
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import queue
import random
import subprocess
import sys
import sysconfig
import threading
import time
from typing import Callable

BASE = Path(__file__).resolve().parent
THREAD_COUNTS = (1, 2, 4, 8, 16, 32, 64)
FULL_COUNT = 50_000_000


@dataclass(frozen=True)
class Counts:
    negative: int = 0
    positive: int = 0
    zero: int = 0

    @property
    def total(self) -> int:
        return self.negative + self.positive + self.zero

    @classmethod
    def combine(cls, items) -> Counts:
        items = list(items)
        return cls(*(sum(getattr(item, key) for item in items)
                     for key in ("negative", "positive", "zero")))


def save_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def generate(path: Path, count: int, seed: int) -> dict:
    """Generate bounded, reproducible input without holding it all in memory."""
    if count < 1:
        raise ValueError("The number of values must be positive.")
    if path.exists():
        raise FileExistsError(f"Refusing to replace existing input: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    negative = positive = zero = 0
    digest = hashlib.sha256()
    with path.open("wb") as output:
        for offset in range(0, count, 100_000):
            lines = []
            for _ in range(min(100_000, count - offset)):
                value = rng.randint(-1_000_000, 1_000_000)
                negative += value < 0
                positive += value > 0
                zero += value == 0
                lines.append(f"{value}\n")
            block = "".join(lines).encode("ascii")
            output.write(block)
            digest.update(block)
            if (offset + len(lines)) % 5_000_000 == 0:
                print(f"Generated {offset + len(lines):,}/{count:,} values", flush=True)
    result = {
        "count": count, "minimum": -1_000_000, "maximum": 1_000_000,
        "seed": seed, "generator": "random.Random(seed).randint",
        "counts": asdict(Counts(negative, positive, zero)),
        "bytes": path.stat().st_size, "sha256": digest.hexdigest(),
        "newline": "LF", "encoding": "ASCII",
    }
    save_json(path.with_suffix(".manifest.json"), result)
    return result


def split_input(path: Path, directory: Path, parts: int, manifest: dict) -> dict:
    """Split in original line order, using bounded output buffers."""
    count = manifest["count"]
    if parts < 1 or count % parts:
        raise ValueError("The value count must be divisible by the number of parts.")
    directory.mkdir(parents=True, exist_ok=True)
    if any(directory.iterdir()):
        raise FileExistsError(f"The output directory must be empty: {directory}")
    per_part = count // parts
    entries = []
    whole_digest = hashlib.sha256()
    with path.open("rb") as source:
        for part in range(parts):
            name = f"part_{part + 1:02d}.txt"
            digest = hashlib.sha256()
            written = 0
            with (directory / name).open("wb") as output:
                remaining = per_part
                while remaining:
                    block_lines = []
                    for _ in range(min(100_000, remaining)):
                        line = source.readline()
                        if not line:
                            raise ValueError("The input ended before its manifest count.")
                        block_lines.append(line)
                    block = b"".join(block_lines)
                    output.write(block)
                    digest.update(block)
                    whole_digest.update(block)
                    written += len(block)
                    remaining -= len(block_lines)
            entries.append({"name": name, "count": per_part,
                            "bytes": written, "sha256": digest.hexdigest()})
        if source.read(1):
            raise ValueError("The input has more lines than its manifest count.")
    if whole_digest.hexdigest() != manifest["sha256"]:
        raise ValueError("The source hash does not match its manifest.")
    result = {"source_sha256": manifest["sha256"], "count": count,
              "counts": manifest["counts"], "parts": entries}
    save_json(directory / "parts.manifest.json", result)
    return result


def run_threads(functions: list[Callable[[], None]]) -> None:
    """Propagate worker failures instead of silently accepting partial counts."""
    errors = []
    error_lock = threading.Lock()

    def protected(function):
        try:
            function()
        except BaseException as exc:
            with error_lock:
                errors.append(exc)

    threads = [threading.Thread(target=protected, args=(function,),
                                name=f"counter-{index + 1}")
               for index, function in enumerate(functions)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    if errors:
        raise RuntimeError(f"Worker failed: {errors[0]}") from errors[0]


def count_file_range(path: Path, start: int, end: int) -> Counts:
    """Count complete lines whose first byte lies in [start, end).

    Inspecting byte start-1 distinguishes an exact line boundary from a partial
    line. Each worker aligns its own start; no central thread reads the file.
    """
    negative = positive = zero = 0
    with path.open("rb", buffering=1024 * 1024) as source:
        if start:
            source.seek(start - 1)
            if source.read(1) != b"\n":
                source.readline()
        position = source.tell()
        while position < end:
            line = source.readline()
            if not line:
                break
            position += len(line)
            value = int(line)
            if value < 0:
                negative += 1
            elif value > 0:
                positive += 1
            else:
                zero += 1
    return Counts(negative, positive, zero)


def task1a(path: Path, threads: int) -> tuple[Counts, dict]:
    size = path.stat().st_size
    results = [Counts()] * threads
    ranges = [(size * index // threads, size * (index + 1) // threads)
              for index in range(threads)]

    def worker(index):
        results[index] = count_file_range(path, *ranges[index])

    run_threads([lambda index=index: worker(index) for index in range(threads)])
    return Counts.combine(results), {"byte_ranges": ranges}


def load_array(path: Path) -> array:
    values = array("i")
    if values.itemsize != 4:
        raise RuntimeError("This experiment requires 32-bit array('i') values.")
    with path.open("rb") as source:
        for line in source:
            values.append(int(line))
    return values


def task1b(values: array, threads: int, mode: str) -> tuple[Counts, dict]:
    shared = [0, 0, 0]
    lock = threading.Lock()
    partials = [Counts()] * threads
    # Views do not copy the preloaded integer array. Every worker owns its view.
    views = [memoryview(values)[len(values) * index // threads:
                                len(values) * (index + 1) // threads]
             for index in range(threads)]

    def worker(index):
        if mode == "local":
            negative = positive = zero = 0
            for value in views[index]:
                if value < 0:
                    negative += 1
                elif value > 0:
                    positive += 1
                else:
                    zero += 1
            partials[index] = Counts(negative, positive, zero)
        elif mode == "lock":
            for value in views[index]:
                slot = 0 if value < 0 else 1 if value > 0 else 2
                with lock:
                    shared[slot] += 1
        elif mode == "unsafe":
            for value in views[index]:
                slot = 0 if value < 0 else 1 if value > 0 else 2
                # Read, add, and store are not a single atomic operation.
                shared[slot] += 1
        else:
            raise ValueError(f"Unknown counter mode: {mode}")

    try:
        run_threads([lambda index=index: worker(index) for index in range(threads)])
    finally:
        for view in views:
            view.release()
    counts = Counts.combine(partials) if mode == "local" else Counts(*shared)
    return counts, {"array_length": len(values),
                    "array_bytes": len(values) * values.itemsize,
                    "synchronization": mode, "preload_timed": False}


def task1c(path: Path, workers: int, batch_size: int = 10_000,
           capacity: int = 100) -> tuple[Counts, dict]:
    if batch_size < 1 or capacity < 1:
        raise ValueError("Batch size and queue capacity must be positive.")
    batches = queue.Queue(maxsize=capacity)
    partials = [Counts()] * workers
    errors = []
    error_lock = threading.Lock()

    def reader():
        try:
            with path.open("rb", buffering=1024 * 1024) as source:
                batch = []
                for line in source:
                    batch.append(line)
                    if len(batch) == batch_size:
                        batches.put(batch)
                        batch = []
                if batch:
                    batches.put(batch)
            batches.shutdown()
        except BaseException as exc:
            with error_lock:
                errors.append(exc)
            batches.shutdown(immediate=True)

    def worker(index):
        negative = positive = zero = 0
        try:
            while True:
                try:
                    batch = batches.get()
                except queue.ShutDown:
                    break
                for line in batch:
                    value = int(line)
                    if value < 0:
                        negative += 1
                    elif value > 0:
                        positive += 1
                    else:
                        zero += 1
                batches.task_done()
        except BaseException as exc:
            with error_lock:
                errors.append(exc)
            batches.shutdown(immediate=True)
        partials[index] = Counts(negative, positive, zero)

    run_threads([reader] + [lambda index=index: worker(index)
                             for index in range(workers)])
    if errors:
        raise RuntimeError(f"Pipeline failed: {errors[0]}") from errors[0]
    return Counts.combine(partials), {
        "reader_threads": 1, "worker_threads": workers,
        "batch_size": batch_size, "queue_capacity_batches": capacity,
        "max_queued_lines": batch_size * capacity,
    }


def count_buffer(data: bytes) -> Counts:
    """Parse a single byte buffer without creating a list of lines."""
    negative = positive = zero = 0
    start = 0
    size = len(data)
    while start < size:
        end = data.find(b"\n", start)
        if end == -1:
            end = size
        value = int(data[start:end])
        if value < 0:
            negative += 1
        elif value > 0:
            positive += 1
        else:
            zero += 1
        start = end + 1
    return Counts(negative, positive, zero)


def task2(files: list[Path], threads: int) -> tuple[Counts, dict]:
    partials = [Counts()] * threads
    timings = [[] for _ in range(threads)]
    origin = time.perf_counter()

    def worker(index):
        result = []
        for path in files[index::threads]:
            read_started = time.perf_counter()
            with path.open("rb") as source:
                data = source.read()  # One read operation and one byte buffer.
            read_finished = time.perf_counter()
            result.append(count_buffer(data))
            parse_finished = time.perf_counter()
            timings[index].append({
                "file": path.name, "bytes": len(data),
                "read_start": read_started - origin,
                "read_seconds": read_finished - read_started,
                "parse_seconds": parse_finished - read_finished,
            })
            del data  # At most one whole-file buffer per worker.
        partials[index] = Counts.combine(result)

    run_threads([lambda index=index: worker(index) for index in range(threads)])
    return Counts.combine(partials), {"files": [str(path) for path in files],
                                     "file_timings": sum(timings, [])}


def peak_memory_bytes() -> int:
    """Process lifetime peak resident memory, including the interpreter."""
    if sys.platform == "win32":
        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (field, ctypes.c_size_t) for field in (
                    "PeakWorkingSetSize", "WorkingSetSize",
                    "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
                    "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
                    "PagefileUsage", "PeakPagefileUsage")]
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE,
                                              ctypes.POINTER(ProcessMemoryCounters),
                                              wintypes.DWORD]
        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(),
                                         ctypes.byref(counters), counters.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        return counters.PeakWorkingSetSize
    import resource
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak if sys.platform == "darwin" else peak * 1024


def runtime_info() -> dict:
    return {"version": sys.version, "executable": sys.executable,
            "implementation": platform.python_implementation(),
            "free_threaded_build": sysconfig.get_config_var("Py_GIL_DISABLED") == 1,
            "gil_enabled": getattr(sys, "_is_gil_enabled", lambda: True)(),
            "logical_processors": os.cpu_count(), "platform": platform.platform()}


def benchmark(args) -> dict:
    runtime = runtime_info()
    if args.require_free_threaded and (not runtime["free_threaded_build"]
                                       or runtime["gil_enabled"]):
        raise RuntimeError("Use a free-threaded Python build with the GIL disabled.")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
    values = None
    preload_seconds = 0.0
    if args.task == "1b":
        preload_started = time.perf_counter()
        values = load_array(args.input)
        preload_seconds = time.perf_counter() - preload_started
    files = []
    if args.task == "2":
        if not args.cold_confirmation:
            raise ValueError("Task 2 requires --cold-confirmation describing the reconnect.")
        files = [args.input / f"part_{number:02d}.txt" for number in range(1, 9)]
        if any(not path.is_file() for path in files):
            raise FileNotFoundError("Task 2 requires part_01.txt through part_08.txt.")
        # Do not read or hash USB input before the cold-cache measurement.
    cpu_started = time.process_time()
    started = time.perf_counter()
    if args.task == "1a":
        counts, details = task1a(args.input, args.threads)
    elif args.task == "1b":
        counts, details = task1b(values, args.threads, args.mode)
    elif args.task == "1c":
        counts, details = task1c(args.input, args.threads, args.batch_size, args.capacity)
    else:
        counts, details = task2(files, args.threads)
    seconds = time.perf_counter() - started
    cpu_seconds = time.process_time() - cpu_started
    peak = peak_memory_bytes()
    correct = asdict(counts) == manifest["counts"] and counts.total == manifest["count"]
    result = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "task": args.task, "mode": args.mode if args.task == "1b" else None,
        "threads": args.threads, "repetition": args.repetition,
        "role": args.role, "wall_seconds": seconds, "cpu_seconds": cpu_seconds,
        "average_cpu_cores": cpu_seconds / seconds,
        "peak_memory_bytes": peak, "peak_memory_mib": peak / (1024 ** 2),
        "memory_metric": "process lifetime peak resident working set",
        "counts": asdict(counts), "total": counts.total,
        "expected_counts": manifest["counts"], "correct": correct,
        "input_sha256": manifest["sha256"], "input": str(args.input.resolve()),
        "input_count": manifest["count"], "preload_seconds_excluded": preload_seconds,
        "source_sha256": sha256_file(Path(__file__)), "runtime": runtime,
        "cold_confirmation": args.cold_confirmation if args.task == "2" else None,
        "details": details,
    }
    if args.output:
        save_json(args.output, result)
    print(json.dumps(result), flush=True)
    if not correct and not (args.task == "1b" and args.mode == "unsafe"):
        raise RuntimeError("Incorrect totals: this result must not be accepted.")
    return result


def suite(args) -> None:
    """Run configurations sequentially, each in a fresh Python process."""
    configurations = []
    for task in ("1a", "1c"):
        configurations.extend((task, threads, "local", 1, "required")
                              for threads in THREAD_COUNTS)
    logical = os.cpu_count() or 1
    for mode in ("unsafe", "lock", "local"):
        configurations.append(("1b", 1, mode, 1, "additional_baseline"))
        configurations.extend(("1b", logical, mode, rep, "required")
                              for rep in range(1, 4 if mode == "unsafe" else 2))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for index, (task, threads, mode, repetition, role) in enumerate(configurations, 1):
        name = f"task{task}_{mode}_{threads:02d}t_r{repetition}"
        output = args.output_dir / f"{name}.json"
        if output.exists():
            previous = json.loads(output.read_text(encoding="utf-8"))
            if previous["source_sha256"] != sha256_file(Path(__file__)):
                raise RuntimeError(f"Source changed since {output}; choose another output directory.")
            print(f"[{index}/{len(configurations)}] Already completed: {name}", flush=True)
            continue
        command = [sys.executable, str(Path(__file__)), "run", task,
                   "--input", str(args.input), "--manifest", str(args.manifest),
                   "--threads", str(threads), "--mode", mode,
                   "--repetition", str(repetition), "--role", role,
                   "--output", str(output), "--require-free-threaded"]
        print(f"[{index}/{len(configurations)}] Running {name}", flush=True)
        completed = subprocess.run(command, text=True, encoding="utf-8", capture_output=True)
        (args.output_dir / f"{name}.log").write_text(
            "$ " + subprocess.list2cmdline(command) + "\n" + completed.stdout + completed.stderr,
            encoding="utf-8")
        if completed.returncode:
            raise RuntimeError(f"Failed: {name}\n{completed.stderr}")
        result = json.loads(output.read_text(encoding="utf-8"))
        print(f"  {result['wall_seconds']:.3f} s | {result['peak_memory_mib']:.1f} MiB | "
              f"total={result['total']:,} | correct={result['correct']}", flush=True)


def race_demo() -> dict:
    """A controlled schedule explains lost updates; it is not a benchmark."""
    counter = [0]
    both_read = threading.Barrier(2)

    def worker():
        old = counter[0]
        both_read.wait()
        counter[0] = old + 1

    run_threads([worker, worker])
    result = {"demonstration_only": True, "expected": 2, "observed": counter[0],
              "explanation": "Both threads read zero before either writes one."}
    print(json.dumps(result))
    return result


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate", help="Generate the complete deterministic input.")
    gen.add_argument("--output", type=Path, default=BASE / "data/numbers.txt")
    gen.add_argument("--count", type=int, default=FULL_COUNT)
    gen.add_argument("--seed", type=int, default=243)
    split = sub.add_parser("split", help="Split input into eight consecutive files.")
    split.add_argument("--input", type=Path, default=BASE / "data/numbers.txt")
    split.add_argument("--output-dir", type=Path, default=BASE / "data/parts")
    split.add_argument("--parts", type=int, default=8)
    split.add_argument("--manifest", type=Path, default=BASE / "data/numbers.manifest.json")
    run = sub.add_parser("run", help="Measure one task/configuration.")
    run.add_argument("task", choices=("1a", "1b", "1c", "2"))
    run.add_argument("--input", type=Path, default=BASE / "data/numbers.txt")
    run.add_argument("--manifest", type=Path, default=BASE / "data/numbers.manifest.json")
    run.add_argument("--threads", type=int, default=1)
    run.add_argument("--mode", choices=("unsafe", "lock", "local"), default="local")
    run.add_argument("--batch-size", type=int, default=10_000)
    run.add_argument("--capacity", type=int, default=100)
    run.add_argument("--repetition", type=int, default=1)
    run.add_argument("--role", default="required")
    run.add_argument("--output", type=Path)
    run.add_argument("--cold-confirmation")
    run.add_argument("--require-free-threaded", action="store_true")
    local = sub.add_parser("suite", help="Run every local configuration in a fresh process.")
    local.add_argument("--input", type=Path, default=BASE / "data/numbers.txt")
    local.add_argument("--manifest", type=Path, default=BASE / "data/numbers.manifest.json")
    local.add_argument("--output-dir", type=Path, default=BASE / "results/local")
    sub.add_parser("runtime", help="Show interpreter and GIL information.")
    sub.add_parser("race-demo", help="Explain a lost update with a controlled schedule.")
    args = parser.parse_args()
    if hasattr(args, "threads") and args.threads < 1:
        parser.error("--threads must be positive")
    if args.command == "generate":
        print(json.dumps(generate(args.output, args.count, args.seed), indent=2))
    elif args.command == "split":
        manifest = json.loads(args.manifest.read_text(encoding="utf-8-sig"))
        print(json.dumps(split_input(args.input, args.output_dir, args.parts, manifest), indent=2))
    elif args.command == "run":
        benchmark(args)
    elif args.command == "suite":
        suite(args)
    elif args.command == "runtime":
        print(json.dumps(runtime_info(), indent=2))
    elif args.command == "race-demo":
        race_demo()


if __name__ == "__main__":
    main()
