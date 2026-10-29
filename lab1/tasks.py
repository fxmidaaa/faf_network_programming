"""The four counting tasks and a controlled lost-update demonstration.

1a: independent file ranges. 1b: shared, locked, or private array counters.
1c: a bounded producer-consumer queue. 2: whole-file buffers from USB storage.
All workers are OS threads and use only the Python standard library.
"""

from array import array
import json
from pathlib import Path
import queue
import threading
import time

from common import Counts, run_threads


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

