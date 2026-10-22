"""Record three physical reconnects and run each required USB configuration.

The observer watches drive-letter presence only. It never reads input data before
the measured child starts. Safe ejection and physical unplugging are human actions.
"""

import argparse
import ctypes
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time

import lab


def utc():
    return datetime.now(timezone.utc).isoformat()


def present(letter):
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    return bool(mask & (1 << (ord(letter.upper()) - ord("A"))))


def wait_for_state(letter, expected, deadline):
    while present(letter) != expected:
        if time.monotonic() > deadline:
            raise TimeoutError("Timed out waiting for the drive reconnect.")
        time.sleep(.2)
    return utc()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("D:/faf_network_programming/lab1"))
    parser.add_argument("--output-dir", type=Path, default=lab.BASE / "results/usb")
    parser.add_argument("--timeout", type=int, default=3600)
    args = parser.parse_args()
    letter = args.input.drive[:1]
    if sys.platform != "win32" or not letter:
        raise RuntimeError("This reconnect observer requires a Windows drive letter.")
    runtime = lab.runtime_info()
    if not runtime["free_threaded_build"] or runtime["gil_enabled"]:
        raise RuntimeError("Run the campaign with free-threaded Python and the GIL disabled.")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for threads in (1, 2, 4):
        output = args.output_dir / f"task2_{threads:02d}t.json"
        if output.exists():
            print(f"Already completed: {threads} USB thread(s)", flush=True)
            continue
        print(f"ACTION REQUIRED: safely eject {letter}:, physically unplug it, then reconnect it. "
              f"Next measurement: {threads} thread(s).", flush=True)
        deadline = time.monotonic() + args.timeout
        observer_started = utc()
        was_present = present(letter)
        removed = wait_for_state(letter, False, deadline)
        print("Observed drive disappearance; waiting for reconnection.", flush=True)
        reconnected = wait_for_state(letter, True, deadline)
        # Allow the filesystem to finish mounting. Only metadata is inspected by lab.py.
        time.sleep(2)
        observation = {
            "threads": threads, "drive_letter": letter,
            "observer_started_utc": observer_started, "initially_present": was_present,
            "removed_at_utc": removed, "reconnected_at_utc": reconnected,
            "observed_absent_then_present": True,
            "method": "GetLogicalDrives, 200 ms polling; no dataset reads before measurement",
            "human_instruction": "Safely eject, physically unplug, reconnect; do not open input files",
            "limitation": "Drive-letter observation corroborates removal; physical action is performed by the user.",
        }
        lab.save_json(args.output_dir / f"reconnect_{threads:02d}t.json", observation)
        confirmation = (f"User instructed to safely eject and physically reconnect. "
                        f"Drive absence observed {removed}; reappearance observed {reconnected}.")
        command = [sys.executable, str(lab.BASE / "lab.py"), "run", "2",
                   "--input", str(args.input), "--threads", str(threads),
                   "--require-free-threaded", "--cold-confirmation", confirmation,
                   "--output", str(output)]
        print(f"Starting cold USB measurement with {threads} thread(s).", flush=True)
        completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
        (args.output_dir / f"task2_{threads:02d}t.log").write_text(
            "$ " + subprocess.list2cmdline(command) + "\n" + completed.stdout + completed.stderr,
            encoding="utf-8")
        if completed.returncode:
            raise RuntimeError(completed.stderr)
        result = json.loads(output.read_text(encoding="utf-8"))
        print(f"FINISHED: {threads} thread(s), {result['wall_seconds']:.3f} s, "
              f"{result['peak_memory_mib']:.1f} MiB, total={result['total']:,}, "
              f"correct={result['correct']}", flush=True)
    print("All three cold USB measurements are complete.", flush=True)


if __name__ == "__main__":
    main()
