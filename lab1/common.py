"""Shared counters, file helpers, and worker error handling."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import threading
from typing import Callable

BASE = Path(__file__).resolve().parent
THREAD_COUNTS = (1, 2, 4, 8, 16, 32, 64)
FULL_COUNT = 50_000_000
SOURCE_FILES = ("benchmark.py", "common.py", "dataset.py", "lab.py", "tasks.py")


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


def source_sha256() -> str:
    """Fingerprint every runtime module, in a stable filename order."""
    digest = hashlib.sha256()
    for name in SOURCE_FILES:
        digest.update(name.encode("utf-8") + b"\0")
        digest.update((BASE / name).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()
