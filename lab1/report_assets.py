"""Generate publication figures from recorded measurements, outside benchmarks."""

from pathlib import Path
import os

# Keep plotting caches inside the project, separate from the counting runtime.
_cache = Path(__file__).resolve().parent / "tmp/matplotlib"
_cache.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_cache))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
import numpy as np

COLORS = {"1a": "#1764a0", "1c": "#008675", "2": "#8c4b9b",
          "local": "#008675", "lock": "#c27b16", "unsafe": "#c54c51"}
INK = "#182e45"


def setup():
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 12,
        "axes.titlesize": 13, "axes.labelsize": 12,
        "xtick.labelsize": 11, "ytick.labelsize": 11,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.edgecolor": "#9ba9b4", "text.color": INK,
        "axes.labelcolor": INK, "axes.titleweight": "bold",
        "grid.color": "#dce3e8", "grid.alpha": .8,
        "savefig.facecolor": "white",
    })


def save(fig, directory, name):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    fig.savefig(directory / f"{name}.png", dpi=220, bbox_inches="tight")
    fig.savefig(directory / f"{name}.svg", bbox_inches="tight")
    plt.close(fig)
    return directory / f"{name}.png"


def scaling(rows, directory, task):
    rows = sorted(rows, key=lambda row: row["threads"])
    threads = [row["threads"] for row in rows]
    elapsed = [row["wall_seconds"] for row in rows]
    metrics = [elapsed, [elapsed[0] / value for value in elapsed],
               [row["peak_memory_mib"] for row in rows]]
    names = [("Execution time", "Seconds"), ("Speed-up", "T(1) / T(p)"),
             ("Peak resident memory", "MiB")]
    fig, axes = plt.subplots(1, 3, figsize=(11.8, 3.25))
    for axis, values, (title, label) in zip(axes, metrics, names):
        axis.plot(threads, values, "o-", color=COLORS[task], lw=2.2, markersize=6)
        axis.set_xscale("log", base=2)
        axis.set_xticks(threads, list(map(str, threads)))
        axis.set(title=title, ylabel=label,
                 xlabel="Workers (+ 1 reader)" if task == "1c" else "Threads")
        axis.grid(axis="y")
        axis.set_ylim(bottom=0)
        if task == "1a":
            axis.axvline(24, color="#b5bcc4", lw=1, ls=":")
            axis.axvline(32, color="#b5bcc4", lw=1, ls="--")
    fig.tight_layout(w_pad=1.7)
    return save(fig, directory, f"task{task}_scaling")


def counter_comparison(rows, directory):
    fig, axes = plt.subplots(1, 3, figsize=(11.8, 3.6))
    p = max(row["threads"] for row in rows)
    for mode in ("local", "lock", "unsafe"):
        baseline = next(row for row in rows if row["mode"] == mode and row["threads"] == 1)
        parallel = [row for row in rows if row["mode"] == mode and row["threads"] == p]
        duration = np.mean([row["wall_seconds"] for row in parallel])
        memory = np.mean([row["peak_memory_mib"] for row in parallel])
        label = {"local": "Private counters", "lock": "One shared lock",
                 "unsafe": "Unsafe (incorrect)"}[mode]
        series = [[baseline["wall_seconds"], duration],
                  [1, baseline["wall_seconds"] / duration],
                  [baseline["peak_memory_mib"], memory]]
        for axis, values in zip(axes, series):
            axis.plot([1, p], values, "o--" if mode == "unsafe" else "o-",
                      color=COLORS[mode], lw=2.1, label=label)
    for axis, title, ylabel in zip(axes,
                                  ("Execution time", "Speed-up by method", "Peak resident memory"),
                                  ("Seconds (log scale)", "T(1) / T(p) (log scale)", "MiB")):
        axis.set(title=title, ylabel=ylabel, xlabel="Threads")
        axis.set_xticks([1, p], ["1", str(p)])
        axis.grid(axis="y")
    axes[0].set_yscale("log")
    axes[1].set_yscale("log")
    axes[2].set_ylim(bottom=0)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, ncols=3, loc="upper center", fontsize=11,
               frameon=False, bbox_to_anchor=(.5, 1.08))
    fig.tight_layout(w_pad=1.5)
    return save(fig, directory, "task1b_comparison")


def architecture(directory):
    fig, axis = plt.subplots(figsize=(11.5, 4.0))
    axis.set(xlim=(0, 12), ylim=(0, 4.2))
    axis.axis("off")
    layouts = [
        ("1a", "One file", "Independent byte ranges", "Private counts", "Reduction"),
        ("1b", "Preloaded int array", "Unsafe / locked / private", "Count with 32 threads", "Compare"),
        ("1c", "One reader", "Queue: 100 x 10,000 lines", "N consumers", "Reduction"),
        ("2", "USB: eight files", "8 / N files per thread", "One buffer per thread", "Reduction"),
    ]
    for row, cells in enumerate(layouts):
        task, *labels = cells
        y = 3.55 - row * 1.02
        color = COLORS.get(task, "#c27b16")
        axis.text(0, y + .2, f"{task}", fontsize=14, fontweight="bold", color=color)
        for column, label in enumerate(labels):
            x = .65 + column * 2.85
            width = 2.55 if column < 3 else 2.0
            axis.add_patch(FancyBboxPatch((x, y - .08), width, .66,
                                          boxstyle="round,pad=0.06,rounding_size=0.08",
                                          linewidth=1.2, edgecolor=color,
                                          facecolor="#f2f6f9"))
            axis.text(x + width / 2, y + .25, label, ha="center", va="center", fontsize=11)
            if column < 3:
                axis.add_patch(FancyArrowPatch((x + width + .07, y + .25),
                                               (x + 2.75, y + .25),
                                               arrowstyle="-|>", mutation_scale=12,
                                               color=color, lw=1.1))
    fig.tight_layout(pad=.4)
    return save(fig, directory, "program_architecture")


def usb_timeline(rows, directory):
    rows = sorted(rows, key=lambda row: row["threads"])
    fig, axes = plt.subplots(3, 1, figsize=(11.7, 5.6), sharex=True)
    for axis, row in zip(axes, rows):
        threads = row["threads"]
        for number in range(1, 9):
            timing = next(item for item in row["details"]["file_timings"]
                          if item["file"] == f"part_{number:02d}.txt")
            worker = (number - 1) % threads
            start = timing["read_start"]
            axis.barh(worker, timing["read_seconds"], left=start, height=.6,
                      color="#8c4b9b", edgecolor="white", linewidth=.4)
            axis.barh(worker, timing["parse_seconds"],
                      left=start + timing["read_seconds"], height=.6,
                      color="#008675", edgecolor="white", linewidth=.4)
        axis.set_yticks(range(threads), [f"W{n + 1}" for n in range(threads)])
        axis.set_title(f"{threads} thread(s): {row['wall_seconds']:.3f} s", loc="left", fontsize=12)
        axis.invert_yaxis()
        axis.grid(axis="x")
    axes[-1].set_xlabel("Seconds since file processing started")
    axes[0].plot([], [], color="#8c4b9b", lw=8, label="Read + file open/close")
    axes[0].plot([], [], color="#008675", lw=8, label="Parse + count")
    axes[0].legend(loc="lower right", bbox_to_anchor=(1, 1.02),
                   ncols=2, fontsize=10, frameon=False)
    fig.tight_layout(h_pad=1.1)
    return save(fig, directory, "usb_read_parse_timeline")


def storage_controls(cold, controls, directory):
    rows = [("USB cold", cold)]
    for row in controls:
        label = "USB warm" if row["role"] == "additional_warm_control" else "NVMe (same parser)"
        rows.append((label, row))
    fig, axis = plt.subplots(figsize=(11.5, 2.5))
    for index, (label, row) in enumerate(rows):
        read = sum(item["read_seconds"] for item in row["details"]["file_timings"])
        parse = sum(item["parse_seconds"] for item in row["details"]["file_timings"])
        axis.barh(index, read, color="#8c4b9b", label="Read" if index == 0 else None, height=.55)
        axis.barh(index, parse, left=read, color="#008675",
                  label="Parse + count" if index == 0 else None, height=.55)
        axis.text(read + parse + .1, index, f"{row['wall_seconds']:.3f} s", va="center", fontsize=11)
    axis.set_yticks(range(len(rows)), [label for label, _ in rows])
    axis.invert_yaxis()
    axis.set_xlabel("Seconds, one thread (identical buffer parser)")
    axis.grid(axis="x")
    axis.margins(x=.17)
    axis.legend(loc="lower right", ncols=2, frameon=False, fontsize=11)
    fig.tight_layout()
    return save(fig, directory, "storage_controls")


def evidence(local, usb, dataset, test_log, directory):
    baseline = next(row for row in local if row["task"] == "1a" and row["threads"] == 1)
    best = min((row for row in local if row["task"] == "1a"), key=lambda row: row["wall_seconds"])
    private = next(row for row in local if row["task"] == "1b"
                   and row["mode"] == "local" and row["threads"] == 32)
    unsafe = next(row for row in local if row["task"] == "1b"
                  and row["mode"] == "unsafe" and row["threads"] == 32)
    test_line = next(line for line in test_log.splitlines() if line.startswith("Ran "))
    lines = [
        "RECORDED EXECUTION EVIDENCE", "Rendered from saved JSON measurements and tests.log",
        "", baseline["runtime"]["version"].split(" [MSC")[0],
        "free_threaded_build=true | gil_enabled=false", test_line + " | OK",
        "", "Full input: 50,000,000 integers | seed=243",
        f"negative={dataset['counts']['negative']:,}  positive={dataset['counts']['positive']:,}  zero={dataset['counts']['zero']}",
        "", "Task     Threads     Seconds       Total          Correct",
    ]
    for label, row in [("1a", baseline), ("1a", best), ("1b/local", private),
                       ("1b/unsafe", unsafe)] + [("2/USB", row) for row in usb]:
        lines.append(f"{label:<10} {row['threads']:>3}       {row['wall_seconds']:>8.3f}     {row['total']:>10,}      {row['correct']}")
    lines.extend(["", "Input SHA-256:", dataset["sha256"]])
    fig = plt.figure(figsize=(11.4, 5.7), facecolor="#122538")
    fig.text(.035, .95, "\n".join(lines), color="#e6f0f7", family="DejaVu Sans Mono",
             fontsize=12, va="top", linespacing=1.4)
    target = Path(directory) / "execution_evidence.png"
    fig.savefig(target, dpi=200, facecolor=fig.get_facecolor(),
                bbox_inches="tight", pad_inches=.2)
    plt.close(fig)
    return target
