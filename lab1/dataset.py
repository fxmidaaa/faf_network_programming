"""Reproducible input generation, splitting, and untimed array loading."""

from array import array
from dataclasses import asdict
import hashlib
from pathlib import Path
import random

from common import Counts, save_json


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


def load_array(path: Path) -> array:
    values = array("i")
    if values.itemsize != 4:
        raise RuntimeError("This experiment requires 32-bit array('i') values.")
    with path.open("rb") as source:
        for line in source:
            values.append(int(line))
    return values

