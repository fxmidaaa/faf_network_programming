"""Concurrency in Practice: command-line entry point for all experiments."""

import argparse
import json
from pathlib import Path
import sys

from benchmark import benchmark, runtime_info, suite
from common import BASE, FULL_COUNT
from dataset import generate, split_input
from tasks import race_demo


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
