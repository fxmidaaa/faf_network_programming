"""Correctness tests for counting algorithms and the command-line workflow."""

from array import array
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import common
from benchmark import peak_memory_bytes
from common import Counts
from dataset import generate, load_array, split_input
from tasks import count_buffer, count_file_range, race_demo, task1a, task1b, task1c, task2


def reference(values):
    return Counts(sum(value < 0 for value in values),
                  sum(value > 0 for value in values),
                  sum(value == 0 for value in values))


class CountingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.values = [-1_000_000, 0, 1, -7, 1_000_000, 0, -9, 12, -123456]
        self.expected = reference(self.values)
        self.path = self.root / "numbers.txt"
        self.path.write_bytes("\n".join(map(str, self.values)).encode("ascii"))

    def tearDown(self):
        self.temporary.cleanup()

    def test_every_possible_two_way_byte_boundary(self):
        size = self.path.stat().st_size
        for boundary in range(size + 1):
            with self.subTest(boundary=boundary):
                counts = Counts.combine([
                    count_file_range(self.path, 0, boundary),
                    count_file_range(self.path, boundary, size)])
                self.assertEqual(counts, self.expected)

    def test_more_threads_than_lines_and_bytes(self):
        for threads in (1, 2, 4, 8, 16, 32, 64):
            with self.subTest(threads=threads):
                self.assertEqual(task1a(self.path, threads)[0], self.expected)

    def test_crlf_and_trailing_newline(self):
        self.path.write_bytes(("\r\n".join(map(str, self.values)) + "\r\n").encode("ascii"))
        self.assertEqual(task1a(self.path, 16)[0], self.expected)
        self.assertEqual(count_buffer(self.path.read_bytes()), self.expected)

    def test_array_is_loaded_exactly(self):
        self.assertEqual(list(load_array(self.path)), self.values)

    def test_protected_and_private_counters(self):
        values = array("i", self.values * 1_000)
        expected = reference(values)
        for mode in ("lock", "local"):
            for threads in (1, 2, 8, 32):
                with self.subTest(mode=mode, threads=threads):
                    self.assertEqual(task1b(values, threads, mode)[0], expected)
        self.assertEqual(task1b(values, 1, "unsafe")[0], expected)

    def test_bounded_queue_and_partial_last_batch(self):
        for workers, batch, capacity in ((1, 1, 1), (8, 2, 1), (64, 10_000, 100)):
            with self.subTest(workers=workers, batch=batch):
                counts, _ = task1c(self.path, workers, batch, capacity)
                self.assertEqual(counts, self.expected)

    def test_pipeline_propagates_parse_failure_and_stops(self):
        self.path.write_bytes(b"1\ninvalid\n-1\n" * 100)
        with self.assertRaises(RuntimeError):
            task1c(self.path, 4, batch_size=1, capacity=1)

    def test_range_propagates_parse_failure(self):
        self.path.write_bytes(b"invalid\n")
        with self.assertRaises(RuntimeError):
            task1a(self.path, 4)

    def test_buffer_parser_edge_cases(self):
        for data, expected in ((b"", Counts()), (b"0", Counts(zero=1)),
                               (b"-1000000\n1000000\n0\n", Counts(1, 1, 1))):
            with self.subTest(data=data):
                self.assertEqual(count_buffer(data), expected)

    def test_many_files_and_each_assignment(self):
        files = []
        for number in range(8):
            path = self.root / f"part_{number + 1:02d}.txt"
            path.write_bytes(self.path.read_bytes())
            files.append(path)
        expected = Counts.combine([self.expected] * 8)
        for threads in (1, 2, 4):
            counts, details = task2(files, threads)
            self.assertEqual(counts, expected)
            self.assertEqual(len(details["file_timings"]), 8)
            self.assertEqual({row["file"] for row in details["file_timings"]},
                             {path.name for path in files})

    def test_generation_and_order_preserving_split(self):
        path = self.root / "generated.txt"
        manifest = generate(path, 80, seed=243)
        values = list(map(int, path.read_bytes().splitlines()))
        self.assertEqual(len(values), 80)
        self.assertTrue(all(-1_000_000 <= value <= 1_000_000 for value in values))
        self.assertEqual(manifest["counts"], asdict(reference(values)))
        self.assertEqual(manifest["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        directory = self.root / "parts"
        parts = split_input(path, directory, 8, manifest)
        combined = b"".join((directory / part["name"]).read_bytes()
                             for part in parts["parts"])
        self.assertEqual(combined, path.read_bytes())
        self.assertTrue(all(part["count"] == 10 for part in parts["parts"]))
        with self.assertRaises(FileExistsError):
            generate(path, 80, seed=243)
        with self.assertRaises(FileExistsError):
            split_input(path, directory, 8, manifest)

    def test_controlled_race_explains_a_lost_update(self):
        result = race_demo()
        self.assertEqual(result["expected"], 2)
        self.assertEqual(result["observed"], 1)

    def test_peak_memory_is_available(self):
        self.assertGreater(peak_memory_bytes(), 0)


class WorkflowTests(unittest.TestCase):
    def test_commands_generate_split_and_run_every_task(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def command(*arguments):
                completed = subprocess.run(
                    [sys.executable, "-B", str(common.BASE / "lab.py"), *map(str, arguments)],
                    cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=15)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                return json.loads(completed.stdout)

            source = root / "numbers.txt"
            manifest = command("generate", "--count", 80, "--seed", 243, "--output", source)
            manifest_path = source.with_suffix(".manifest.json")
            parts = root / "parts"
            command("split", "--input", source, "--manifest", manifest_path,
                    "--output-dir", parts)
            configurations = [
                ("1a", source, ["--threads", 4]),
                ("1b", source, ["--threads", 1, "--mode", "unsafe"]),
                ("1b", source, ["--threads", 4, "--mode", "lock"]),
                ("1b", source, ["--threads", 4, "--mode", "local"]),
                ("1c", source, ["--threads", 4, "--batch-size", 3, "--capacity", 1]),
                ("2", parts, ["--threads", 4, "--cold-confirmation", "Local correctness test"]),
            ]
            for index, (task, input_path, arguments) in enumerate(configurations):
                with self.subTest(task=task, arguments=arguments):
                    output = root / f"run_{index}.json"
                    result = command("run", task, "--input", input_path,
                                     "--manifest", manifest_path, "--output", output, *arguments)
                    self.assertEqual(result["counts"], manifest["counts"])
                    self.assertEqual(result["total"], manifest["count"])
                    self.assertTrue(result["correct"])
                    self.assertEqual(result["source_sha256"], common.source_sha256())
                    self.assertEqual(json.loads(output.read_text()), result)

    def test_source_fingerprint_changes_when_any_runtime_module_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in common.SOURCE_FILES:
                (root / name).write_text("# original\n")
            with patch.object(common, "BASE", root):
                original = common.source_sha256()
                for name in common.SOURCE_FILES:
                    with self.subTest(module=name):
                        (root / name).write_text("# changed\n")
                        self.assertNotEqual(common.source_sha256(), original)
                        (root / name).write_text("# original\n")
                self.assertEqual(common.source_sha256(), original)


if __name__ == "__main__":
    unittest.main(verbosity=2)
