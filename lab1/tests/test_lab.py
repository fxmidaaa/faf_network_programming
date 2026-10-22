"""Correctness tests for boundaries, synchronization, queues, and USB parsing."""

from array import array
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import lab


def reference(values):
    return lab.Counts(sum(value < 0 for value in values),
                      sum(value > 0 for value in values),
                      sum(value == 0 for value in values))


class CountingTests(unittest.TestCase):
    def setUp(self):
        scratch = lab.BASE / "tmp/tests"
        scratch.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=scratch)
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
                counts = lab.Counts.combine([
                    lab.count_file_range(self.path, 0, boundary),
                    lab.count_file_range(self.path, boundary, size)])
                self.assertEqual(counts, self.expected)

    def test_more_threads_than_lines_and_bytes(self):
        for threads in (1, 2, 4, 8, 16, 32, 64):
            with self.subTest(threads=threads):
                self.assertEqual(lab.task1a(self.path, threads)[0], self.expected)

    def test_crlf_and_trailing_newline(self):
        self.path.write_bytes(("\r\n".join(map(str, self.values)) + "\r\n").encode("ascii"))
        self.assertEqual(lab.task1a(self.path, 16)[0], self.expected)
        self.assertEqual(lab.count_buffer(self.path.read_bytes()), self.expected)

    def test_array_is_loaded_exactly(self):
        self.assertEqual(list(lab.load_array(self.path)), self.values)

    def test_protected_and_private_counters(self):
        values = array("i", self.values * 1_000)
        expected = reference(values)
        for mode in ("lock", "local"):
            for threads in (1, 2, 8, 32):
                with self.subTest(mode=mode, threads=threads):
                    self.assertEqual(lab.task1b(values, threads, mode)[0], expected)
        self.assertEqual(lab.task1b(values, 1, "unsafe")[0], expected)

    def test_bounded_queue_and_partial_last_batch(self):
        for workers, batch, capacity in ((1, 1, 1), (8, 2, 1), (64, 10_000, 100)):
            with self.subTest(workers=workers, batch=batch):
                counts, _ = lab.task1c(self.path, workers, batch, capacity)
                self.assertEqual(counts, self.expected)

    def test_pipeline_propagates_parse_failure_and_stops(self):
        self.path.write_bytes(b"1\ninvalid\n-1\n" * 100)
        with self.assertRaises(RuntimeError):
            lab.task1c(self.path, 4, batch_size=1, capacity=1)

    def test_range_propagates_parse_failure(self):
        self.path.write_bytes(b"invalid\n")
        with self.assertRaises(RuntimeError):
            lab.task1a(self.path, 4)

    def test_buffer_parser_edge_cases(self):
        for data, expected in ((b"", lab.Counts()), (b"0", lab.Counts(zero=1)),
                               (b"-1000000\n1000000\n0\n", lab.Counts(1, 1, 1))):
            with self.subTest(data=data):
                self.assertEqual(lab.count_buffer(data), expected)

    def test_many_files_and_each_assignment(self):
        files = []
        for number in range(8):
            path = self.root / f"part_{number + 1:02d}.txt"
            path.write_bytes(self.path.read_bytes())
            files.append(path)
        expected = lab.Counts.combine([self.expected] * 8)
        for threads in (1, 2, 4):
            counts, details = lab.task2(files, threads)
            self.assertEqual(counts, expected)
            self.assertEqual(len(details["file_timings"]), 8)
            self.assertEqual({row["file"] for row in details["file_timings"]},
                             {path.name for path in files})

    def test_generation_and_order_preserving_split(self):
        path = self.root / "generated.txt"
        manifest = lab.generate(path, 80, seed=243)
        values = list(map(int, path.read_bytes().splitlines()))
        self.assertEqual(len(values), 80)
        self.assertTrue(all(-1_000_000 <= value <= 1_000_000 for value in values))
        self.assertEqual(manifest["counts"], lab.asdict(reference(values)))
        self.assertEqual(manifest["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
        directory = self.root / "parts"
        parts = lab.split_input(path, directory, 8, manifest)
        combined = b"".join((directory / part["name"]).read_bytes()
                             for part in parts["parts"])
        self.assertEqual(combined, path.read_bytes())
        self.assertTrue(all(part["count"] == 10 for part in parts["parts"]))
        with self.assertRaises(FileExistsError):
            lab.generate(path, 80, seed=243)
        with self.assertRaises(FileExistsError):
            lab.split_input(path, directory, 8, manifest)

    def test_controlled_race_explains_a_lost_update(self):
        result = lab.race_demo()
        self.assertEqual(result["expected"], 2)
        self.assertEqual(result["observed"], 1)

    def test_peak_memory_is_available(self):
        self.assertGreater(lab.peak_memory_bytes(), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
