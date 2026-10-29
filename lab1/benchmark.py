"""Runtime checks, timing, validation, and sequential measurement campaigns."""

import ctypes
from ctypes import wintypes
from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
import platform
import subprocess
import sys
import sysconfig
import time

from common import BASE, THREAD_COUNTS, save_json, source_sha256
from dataset import load_array
from tasks import task1a, task1b, task1c, task2


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
        "source_sha256": source_sha256(), "runtime": runtime,
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
            if previous["source_sha256"] != source_sha256():
                raise RuntimeError(f"Source changed since {output}; choose another output directory.")
            print(f"[{index}/{len(configurations)}] Already completed: {name}", flush=True)
            continue
        command = [sys.executable, str(BASE / "lab.py"), "run", task,
                   "--input", str(args.input), "--manifest", str(args.manifest),
                   "--threads", str(threads), "--mode", mode,
                   "--repetition", str(repetition), "--role", role,
                   "--output", str(output), "--require-free-threaded"]
        print(f"[{index}/{len(configurations)}] Running {name}", flush=True)
        completed = subprocess.run(command, text=True, encoding="utf-8", capture_output=True)
        if completed.returncode:
            raise RuntimeError(f"Failed: {name}\n{completed.stderr}")
        result = json.loads(output.read_text(encoding="utf-8"))
        print(f"  {result['wall_seconds']:.3f} s | {result['peak_memory_mib']:.1f} MiB | "
              f"total={result['total']:,} | correct={result['correct']}", flush=True)

