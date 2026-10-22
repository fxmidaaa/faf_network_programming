"""Build the English report and illustrations exclusively from recorded evidence."""

from __future__ import annotations

import csv
from html import escape
import json
from pathlib import Path
import re
import statistics

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (HRFlowable, Image, KeepTogether, PageBreak,
                               Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle)

import lab
import report_assets as figures

BASE = Path(__file__).resolve().parent
REPO = "https://github.com/fxmidaaa/faf_network_programming"
NAVY = colors.HexColor("#182e45")
BLUE = colors.HexColor("#1764a0")
TEAL = colors.HexColor("#008675")
GRAY = colors.HexColor("#546575")
LIGHT = colors.HexColor("#edf3f7")
WIDTH = A4[0] - 96


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def load_evidence():
    local = [read(path) for path in sorted((BASE / "results/local").glob("*.json"))]
    usb = [read(BASE / f"results/usb/task2_{p:02d}t.json") for p in (1, 2, 4)]
    reconnect = [read(BASE / f"results/usb/reconnect_{p:02d}t.json") for p in (1, 2, 4)]
    controls = [read(path) for path in sorted((BASE / "results/controls").glob("*.json"))]
    data = read(BASE / "results/numbers.manifest.json")
    hardware = read(BASE / "results/hardware.json")
    copied = read(BASE / "results/usb_copy_verification.json")
    required = {(task, p) for task in ("1a", "1c") for p in lab.THREAD_COUNTS}
    found = {(row["task"], row["threads"]) for row in local if row["task"] in ("1a", "1c")}
    if found != required or len(local) != 22:
        raise ValueError("The complete 22-configuration local measurement set is required.")
    expected_1b = {(mode, 1, 1) for mode in ("unsafe", "lock", "local")}
    expected_1b |= {("unsafe", 32, repetition) for repetition in (1, 2, 3)}
    expected_1b |= {(mode, 32, 1) for mode in ("lock", "local")}
    if {(r["mode"], r["threads"], r["repetition"]) for r in local if r["task"] == "1b"} != expected_1b:
        raise ValueError("Task 1b configurations do not match this 32-processor campaign.")
    source_hash = lab.sha256_file(BASE / "lab.py")
    for row in local + usb + controls:
        if row["source_sha256"] != source_hash or row["input_sha256"] != data["sha256"]:
            raise ValueError("A measurement uses a different source version or dataset.")
        if not row["runtime"]["free_threaded_build"] or row["runtime"]["gil_enabled"]:
            raise ValueError("A measurement did not use free-threaded execution.")
        actual_correct = row["counts"] == data["counts"] and row["total"] == data["count"]
        if row["correct"] != actual_correct:
            raise ValueError("A correctness flag disagrees with the actual counters.")
        unsafe = row["task"] == "1b" and row["mode"] == "unsafe"
        if not unsafe and not actual_correct:
            raise ValueError("A supposedly correct method has incorrect totals.")
    if any(not item["observed_absent_then_present"] for item in reconnect):
        raise ValueError("A USB reconnect observation is missing.")
    if len(copied["files"]) != 8 or not all(item["verified"] for item in copied["files"]):
        raise ValueError("The eight USB copy hashes were not verified.")
    return local, usb, reconnect, controls, data, hardware


class Report:
    def __init__(self):
        styles = getSampleStyleSheet()
        self.body = ParagraphStyle("BodyEnglish", parent=styles["BodyText"],
                                   fontName="Helvetica", fontSize=10.1, leading=14,
                                   textColor=NAVY, spaceAfter=7)
        self.small = ParagraphStyle("SmallEnglish", parent=self.body, fontSize=8.2,
                                    leading=11, spaceAfter=5, textColor=GRAY)
        self.h1 = ParagraphStyle("MainHeading", parent=self.body, fontName="Helvetica-Bold",
                                 fontSize=20, leading=24, spaceAfter=13, textColor=BLUE)
        self.h2 = ParagraphStyle("SubHeading", parent=self.body, fontName="Helvetica-Bold",
                                 fontSize=11.4, leading=15, spaceBefore=8, spaceAfter=6)
        self.cell = ParagraphStyle("TableCell", parent=self.body, fontSize=8.3,
                                   leading=11, spaceAfter=0)
        self.story = []
        self.markdown = []

    def page(self, title):
        self.story += [PageBreak(), Paragraph(escape(title), self.h1)]
        self.markdown += [f"\n## {title}\n"]

    def p(self, text, small=False):
        self.story.append(Paragraph(escape(text), self.small if small else self.body))
        self.markdown.append(text + "\n")

    def h(self, text):
        self.story.append(Paragraph(escape(text), self.h2))
        self.markdown.append(f"\n### {text}\n")

    def table(self, headers, rows, widths=None):
        values = [[Paragraph(escape(str(value)), self.cell) for value in row]
                  for row in [headers] + rows]
        table = Table(values, colWidths=widths, repeatRows=1, hAlign="LEFT")
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), LIGHT),
            ("LINEBELOW", (0, 0), (-1, 0), 1, BLUE),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafb")]),
            ("LINEBELOW", (0, -1), (-1, -1), .5, colors.HexColor("#cdd8e0")),
        ]))
        self.story += [table, Spacer(1, 9)]
        self.markdown += ["| " + " | ".join(map(str, headers)) + " |",
                          "| " + " | ".join("---" for _ in headers) + " |"]
        self.markdown += ["| " + " | ".join(map(str, row)) + " |" for row in rows]
        self.markdown += [""]

    def image(self, path, caption, max_height=270):
        width, height = ImageReader(str(path)).getSize()
        factor = min(WIDTH / width, max_height / height)
        self.story += [Image(str(path), width=width * factor, height=height * factor),
                       Spacer(1, 5), Paragraph(escape(caption), self.small)]
        self.markdown.append(f"![{caption}]({Path(path).relative_to(BASE).as_posix()})\n")

    def qa(self, number, question, answer):
        self.h(f"{number}. {question}")
        self.p(answer)


def cover(report):
    cover_title = ParagraphStyle("CoverTitle", parent=report.body, fontName="Helvetica-Bold",
                                 fontSize=33, leading=39, textColor=NAVY)
    subtitle = ParagraphStyle("CoverSubtitle", parent=report.body,
                               fontSize=14, leading=21, textColor=BLUE)
    report.story += [Spacer(1, 45), Paragraph("NETWORK PROGRAMMING", subtitle),
                     Spacer(1, 13), Paragraph("Laboratory Work 1", subtitle),
                     Spacer(1, 24), Paragraph("Concurrency<br/>in Practice", cover_title),
                     Spacer(1, 22), HRFlowable(width="100%", thickness=3, color=TEAL),
                     Spacer(1, 27)]
    report.markdown += ["# Laboratory Work 1: Concurrency in Practice\n"]
    report.table(["", ""], [
        ["Author", "Rustem Cimendur"], ["Group", "FAF-243"],
        ["Verified", "Cristofor Fistic, asist. univ."],
        ["Implementation", "Python - OS threads - free-threaded CPython"],
        ["Measurement date", "22 October 2026"],
    ], [95, WIDTH - 95])
    report.story.append(Spacer(1, 18))
    report.p("A measured comparison of independent file partitions, shared counters, "
             "a bounded producer-consumer queue, and cold reads from USB storage.")
    report.p("Source code and reproducibility materials:")
    report.story.append(Paragraph(f'<link href="{REPO}" color="#1764a0">{REPO}</link>', report.body))
    report.markdown.append(f"[GitHub repository]({REPO})\n")
    report.story += [Spacer(1, 30)]
    report.p("50,000,000 values | 24 physical cores | 32 logical processors", small=True)


def environment(report, data, hardware):
    report.page("1. Environment and input")
    ram = hardware["system"]["TotalPhysicalMemory"] / 1024 ** 3
    report.table(["Component", "Recorded configuration"], [
        ["Computer", "Lenovo 82WR"],
        ["CPU", "Intel Core i9-13900HX; 24 physical cores, 32 logical processors"],
        ["RAM", f"{ram:.2f} GiB reported by Windows (32 GiB installed class)"],
        ["Internal storage", "Samsung MZVL21T0HCLR-00BL2, approximately 1 TB, NVMe SSD; C:, NTFS"],
        ["USB storage", "Transcend StoreJet, approximately 2 TB, external USB HDD; D:, NTFS; UAS driver"],
        ["USB version", "Device descriptor bcdUSB=0x0310 (USB 3.1); operating at SuperSpeed, not SuperSpeedPlus"],
        ["OS", "Windows 11 Pro, 64-bit, build 26200 (10.0.26200)"],
        ["Counting runtime", "CPython 3.14.5, 64-bit free-threading build; GIL disabled in every measurement"],
        ["Power plan", "Windows Balanced; no fixed CPU frequency or core affinity imposed"],
    ], [96, WIDTH - 96])
    report.p("USB information was obtained from the actual device descriptor and Windows "
             "EX_V2 connection flags. The host controller's version alone would not establish "
             "the connected device's protocol. The storage substitution from a flash stick "
             "to the student's external HDD was accepted by the student before execution.", small=True)
    report.h("Dataset and independent reference")
    report.p("numbers.txt contains exactly 50,000,000 uniformly generated integer draws from "
             "-1,000,000 through 1,000,000, inclusive, one ASCII value per LF-terminated line. "
             "The generator is random.Random(243).randint; its counters are recorded while "
             "generating the file, independently of the counting tasks.")
    report.table(["Negative", "Positive", "Zero", "Total", "File size"], [[
        f"{data['counts']['negative']:,}", f"{data['counts']['positive']:,}",
        str(data["counts"]["zero"]), f"{data['count']:,}",
        f"{data['bytes']:,} B ({data['bytes'] / 1024 ** 2:.2f} MiB)",
    ]], [97, 97, 52, 97, WIDTH - 343])
    report.p("The eight Task 2 files contain 6,250,000 values each in original order. "
             "Their concatenated hash matches numbers.txt; all eight USB copies were "
             "verified before the first physical reconnect.")
    report.p("SHA-256: " + data["sha256"], small=True)


def methods(report, architecture_path):
    report.page("2. Program and measurement method")
    report.image(architecture_path, "Figure 1. Work division and communication in the four tasks.", 200)
    report.h("One command-line program")
    report.p("lab.py selects every task and configuration through arguments. It uses "
             "threading.Thread, threading.Lock, queue.Queue, and a compact array('i'). "
             "No process pool, NumPy counting, or synthetic sleeping workload is used. "
             "Task 1b workers hold non-copying views into the same preloaded integer array.")
    report.h("Timing and CPU work")
    report.p("Each configuration runs sequentially in a fresh process. Wall time uses "
             "perf_counter() and includes thread creation, execution, joining, and final "
             "reduction. Task 1b loading is excluded and recorded separately. Generation, "
             "splitting, JSON output, and plotting are excluded. Process CPU time covers "
             "the same interval; CPU seconds / wall seconds estimates average core use.")
    report.h("Peak memory and speed-up")
    report.p("Memory is the Windows process-lifetime PeakWorkingSetSize, including the "
             "interpreter, buffers, thread state, allocator-retained pages, and Task 1b "
             "preload. It is resident memory, not reserved thread stack address space. "
             "Because it is a lifetime maximum, a transient array resize during the "
             "untimed preload may still determine the reported peak. MiB means 2^20 bytes.")
    report.p("Speed-up is S(p)=T(1)/T(p), within one task and counting method. Extra "
             "one-thread Task 1b baselines make that definition possible. Task 1c's p "
             "counts consumers and excludes its one extra reader. Unsafe speed-up is a "
             "timing diagnostic only: an incorrect count is not useful completed work.")
    report.h("Cache protocol and scope")
    report.p("Local measurements use the normal OS cache, warmed by input preparation. "
             "Every required USB configuration follows safe ejection, physical unplugging, "
             "and reconnection. Input hashes are never read between reconnect and timing. "
             "One observation is collected per required configuration, except three unsafe "
             "Task 1b repetitions. There are no statistical error bars from single observations.")


def task1a_page(report, rows, figure):
    report.page("3. Task 1a - independent file partitions")
    rows = sorted(rows, key=lambda row: row["threads"])
    one = rows[0]
    report.image(figure, "Figure 2. Task 1a. Dotted/ dashed vertical markers indicate 24 physical cores / 32 logical processors.", 190)
    report.table(["Threads", "Time, s", "Speed-up", "Peak, MiB", "Avg. CPU cores"], [
        [r["threads"], f"{r['wall_seconds']:.3f}", f"{one['wall_seconds'] / r['wall_seconds']:.2f}x",
         f"{r['peak_memory_mib']:.1f}", f"{r['average_cpu_cores']:.2f}"] for r in rows
    ], [65, 95, 95, 112, WIDTH - 367])
    t32, t64 = [next(r for r in rows if r["threads"] == p) for p in (32, 64)]
    report.qa(1, "Where does speed-up stop growing?",
              f"Most scaling is obtained by 16-32 threads. The recorded minimum is "
              f"{min(rows, key=lambda r: r['wall_seconds'])['threads']} threads; going from 32 to 64 "
              f"changes time from {t32['wall_seconds']:.3f} to {t64['wall_seconds']:.3f} s "
              f"({(t32['wall_seconds'] - t64['wall_seconds']) / t32['wall_seconds'] * 100:.1f}% less time). "
              "This is a plateau compared with earlier gains. A single run cannot establish "
              "a reliable small advantage. The 24 physical cores and 32 logical contexts "
              "limit useful parallel execution; logical contexts are not equally powerful cores.")
    report.qa(2, "Do 32 and 64 threads help?",
              "In this particular task they still improve the recorded time slightly; it "
              "would be incorrect to claim that they necessarily slow it down. At 64, "
              "oversubscription adds scheduling and startup costs without doubling CPU "
              "capacity. The much larger slowdown in Task 1c is discussed separately.")
    report.qa(3, "Does peak memory depend on thread count?",
              f"Yes: {one['peak_memory_mib']:.1f} MiB at one thread versus "
              f"{t64['peak_memory_mib']:.1f} MiB at 64. Each reader has a 1 MiB file "
              "buffer plus Python and OS thread state. Each worker opens and aligns only "
              "its own interval; the main thread never scans the input for the workers.")


def task1b_page(report, rows, figure):
    report.page("4. Task 1b - synchronization costs")
    report.image(figure, "Figure 3. Method-specific one-thread baselines and 32-thread results. Unsafe 32-thread points are the mean of three incorrect runs; time and speed-up axes are logarithmic.", 195)
    parallel = {mode: [r for r in rows if r["mode"] == mode and r["threads"] == 32]
                for mode in ("local", "lock", "unsafe")}
    names = {"local": "Private", "lock": "Locked", "unsafe": "Unsafe"}
    summary = []
    for mode, results in parallel.items():
        one = next(r for r in rows if r["mode"] == mode and r["threads"] == 1)
        elapsed = statistics.mean(r["wall_seconds"] for r in results)
        summary.append([names[mode], f"{one['wall_seconds']:.3f}", f"{elapsed:.3f}",
                        f"{one['wall_seconds'] / elapsed:.3f}x",
                        f"{statistics.mean(r['peak_memory_mib'] for r in results):.1f}",
                        "Yes" if all(r["correct"] for r in results) else "No"])
    report.table(["Method", "1 thread, s", "32 threads, s", "Speed-up", "Peak, MiB", "Correct"],
                 summary, [72, 82, 92, 75, 93, WIDTH - 414])
    report.h("The three required unsafe runs")
    unsafe = sorted(parallel["unsafe"], key=lambda r: r["repetition"])
    report.table(["Run", "Time, s", "Negative", "Positive", "Zero", "Total", "Lost updates"], [
        [r["repetition"], f"{r['wall_seconds']:.3f}", f"{r['counts']['negative']:,}", f"{r['counts']['positive']:,}",
         r["counts"]["zero"], f"{r['total']:,}", f"{50_000_000 - r['total']:,}"] for r in unsafe
    ], [27, 66, 93, 93, 33, 94, WIDTH - 406])
    ranking = sorted(parallel, key=lambda mode: statistics.mean(r["wall_seconds"] for r in parallel[mode]))
    report.qa(4, "Rank the methods and explain correctness",
              "Recorded time ranking at 32 threads: " + " < ".join(names[mode].lower() for mode in ranking) +
              ". Private counters and the locked version reproduce all three reference totals. "
              "The unsafe runs lose read/add/write updates and fail correctness. CPython's "
              "internal container synchronization protects individual list operations, not "
              "the whole increment. It can still create heavy contention even though the "
              "application has no explicit lock. The explicit lock serializes increments; "
              "private counters avoid per-value sharing and merge only after joining.")
    report.p("The integer array contains 200,000,000 bytes (190.73 MiB). The reported "
             "process peak also includes preload resizing and allocator/interpreter memory. "
             "Loading is excluded from time, not from the lifetime memory peak. This metric "
             "alone cannot attribute the difference to a particular allocation.", small=True)


def task1c_page(report, rows, a_rows, figure):
    report.page("5. Task 1c - producer and consumers")
    rows = sorted(rows, key=lambda r: r["threads"])
    report.image(figure, "Figure 4. Task 1c has one additional reader at every worker count. Queue capacity is 100 batches; batch size is 10,000 raw lines.", 190)
    one = rows[0]
    report.table(["Workers", "Time, s", "Speed-up", "Peak, MiB", "Task 1a time, s"], [
        [r["threads"], f"{r['wall_seconds']:.3f}", f"{one['wall_seconds'] / r['wall_seconds']:.2f}x",
         f"{r['peak_memory_mib']:.1f}",
         f"{next(a['wall_seconds'] for a in a_rows if a['threads'] == r['threads']):.3f}"] for r in rows
    ], [64, 92, 88, 113, WIDTH - 357])
    best = min(rows, key=lambda r: r["wall_seconds"])
    report.qa(5, "How does the pipeline compare with Task 1a?",
              f"The recorded pipeline minimum is {best['wall_seconds']:.3f} s with "
              f"{best['threads']} consumers. One consumer takes {one['wall_seconds']:.3f} s, "
              "but that configuration already has two OS threads: reader and consumer. "
              "It can overlap reading with parsing. At larger counts, Task 1a is much "
              "faster because its readers parse independently. The single producer in "
              "Task 1c caps delivery; extra consumers add queue and scheduling costs. "
              "The 32- and 64-consumer results show that oversubscription can be slower.")
    report.qa(6, "What about one-line batches or an unlimited queue?",
              "One-line batches would replace roughly 5,000 batch transfers with "
              "50,000,000 queue transfers, greatly increasing synchronization and object "
              "overhead. An unlimited queue could retain most of the input as Python "
              "line objects if the reader outruns consumers. The bound applies backpressure "
              "at one million queued lines; active batches are additional to this bound.")
    report.p(f"Memory is not monotonic: the one-consumer peak is {one['peak_memory_mib']:.1f} MiB, "
             f"while two consumers use {rows[1]['peak_memory_mib']:.1f} MiB. A slow consumer "
             "allows more queued lines to accumulate. At high worker counts, additional "
             "thread state and active batches increase the peak again.", small=True)


def task2_page(report, rows, a_rows, reconnect, figure):
    report.page("6. Task 2 - cold USB reads")
    rows = sorted(rows, key=lambda r: r["threads"])
    one = rows[0]
    report.image(figure, "Figure 5. Required cold USB measurements, one observation per configuration. Files are the work units; no text input is read from C: in these runs.", 190)
    report.table(["Threads", "Files / thread", "Time, s", "Speed-up", "Peak, MiB", "Avg. CPU cores"], [
        [r["threads"], 8 // r["threads"], f"{r['wall_seconds']:.3f}",
         f"{one['wall_seconds'] / r['wall_seconds']:.2f}x", f"{r['peak_memory_mib']:.1f}",
         f"{r['average_cpu_cores']:.2f}"] for r in rows
    ], [54, 80, 84, 72, 94, WIDTH - 384])
    report.h("Cold-cache procedure and recorded evidence")
    report.p("Before each configuration the user safely ejected, physically unplugged, "
             "and reconnected the drive as instructed. A separate observer logged drive "
             "disappearance and reappearance using GetLogicalDrives without reading data. "
             "It then started a fresh measurement process after a two-second mount delay. "
             "These OS observations corroborate removal; they do not independently prove "
             "the physical action or rule out background OS activity.")
    report.table(["Threads", "Observed absent (UTC)", "Observed present (UTC)"], [
        [r["threads"], r["removed_at_utc"].split("T")[1].split("+")[0][:8],
         r["reconnected_at_utc"].split("T")[1].split("+")[0][:8]] for r in reconnect
    ], [65, 215, WIDTH - 280])
    report.h("Questions: storage limits and useful concurrency")
    local_one = next(r for r in a_rows if r["threads"] == 1)
    report.p(f"USB with one thread takes {one['wall_seconds']:.3f} s; Task 1a on the "
             f"internal SSD takes {local_one['wall_seconds']:.3f} s "
             f"({one['wall_seconds'] / local_one['wall_seconds']:.2f} times as long). "
             "This ratio alone does not prove I/O dominance: Task 2 uses a whole-buffer "
             "parser and a cold HDD, whereas Task 1a uses buffered lines and a warm NVMe "
             "file. The next page separates read time from parsing and adds matched controls.")
    best = min(rows, key=lambda r: r["wall_seconds"])
    report.p(f"The best observed USB configuration uses {best['threads']} thread(s), "
             f"with speed-up {one['wall_seconds'] / best['wall_seconds']:.2f}x. "
             "Concurrent readers share one HDD mechanism, controller, and USB link; "
             "additional streams may add seeks and cannot multiply its bandwidth. "
             "Independent network waits can overlap without sharing that single disk "
             "mechanism, which explains why the lecture's I/O example need not predict "
             "the same scaling here.")


def storage_diagnosis(report, usb, controls, timeline, control_figure):
    report.page("7. Where the USB time goes")
    one = next(r for r in usb if r["threads"] == 1)
    read_seconds = sum(r["read_seconds"] for r in one["details"]["file_timings"])
    parse_seconds = sum(r["parse_seconds"] for r in one["details"]["file_timings"])
    fraction = read_seconds / (read_seconds + parse_seconds)
    report.image(timeline, "Figure 6. Per-file read and parse intervals on each worker. Overlapping workers share the same horizontal time axis; their durations must not be summed into wall time.", 250)
    report.image(control_figure, "Figure 7. Additional one-thread storage controls use the identical whole-buffer parser. Only the first row belongs to the required cold USB campaign.", 130)
    report.p(f"In the one-thread cold run, reading/opening/closing totals {read_seconds:.3f} s "
             f"({fraction * 100:.1f}% of the read-plus-parse stages), and parsing/counting "
             f"totals {parse_seconds:.3f} s ({(1 - fraction) * 100:.1f}%). "
             f"Average process core use is {one['average_cpu_cores']:.2f}. "
             "Read calls include both transfer work and waiting; parse intervals measure "
             "Python computation. At one thread, these non-overlapping stages provide "
             "stronger evidence than a cross-task wall-time comparison.")
    if fraction >= .6:
        diagnosis = ("This one-thread USB workload is predominantly storage/I/O-limited. "
                     "The same drive still supplies all concurrent readers, so the bottleneck "
                     "does not disappear when more threads are added.")
    elif fraction <= .4:
        diagnosis = ("This Python workload remains predominantly parsing/CPU-limited at one "
                     "thread, despite using a cold external HDD. Storage still contributes "
                     "a measurable cost and can become limiting when several readers compete.")
    else:
        diagnosis = ("This is a mixed CPU-and-storage workload at one thread: neither parsing "
                     "nor reading is negligible. Its classification changes with the work "
                     "division and available storage concurrency.")
    report.p(diagnosis)
    report.p("Controls are diagnostic additions, not replacements for cold USB runs. The "
             "local control reads the same eight parts on NVMe; the warm USB control follows "
             "the completed cold campaign without another reconnect. Per-file timings are "
             "wall-clock stages, not hardware disk-busy counters, so they cannot isolate "
             "controller latency, seek time, OS readahead, or device-internal cache.", small=True)
    return diagnosis


def evidence_page(report, local, usb, data, figure):
    report.page("8. Correctness and execution evidence")
    report.image(figure, "Figure 8. An evidence illustration rendered from the saved execution records and test log, not a desktop screenshot. Original JSON and command output are included in results/.", 300)
    expected = data["counts"]
    report.table(["Configuration group", "Runs", "All three counters match?"], [
        ["Task 1a: all thread counts", "7", "Yes"],
        ["Task 1c: all worker counts", "7", "Yes"],
        ["Task 1b: one-thread baselines", "3", "Yes"],
        ["Task 1b: 32-thread lock / private", "2", "Yes"],
        ["Task 1b: 32-thread unsafe", "3", "No; lost updates recorded explicitly"],
        ["Task 2: three cold USB configurations", "3", "Yes"],
    ], [240, 45, WIDTH - 285])
    report.p(f"Every accepted counting result has negative={expected['negative']:,}, "
             f"positive={expected['positive']:,}, zero={expected['zero']}, and total=50,000,000. "
             "Checking only the sum would be insufficient: a skipped value and a duplicate "
             "could cancel. Incorrect unsafe outputs are retained as the required race experiment.")
    report.p("The 13 automated tests cover every possible two-way byte cut in an adversarial "
             "small file, more threads than lines, LF/CRLF and a missing final newline, "
             "array loading, protected counters, bounded queue draining, worker failures, "
             "whole-buffer parsing, eight-file assignment, ordered splitting, and a controlled "
             "lost update. The controlled demonstration is separate from all benchmarks.", small=True)


def control_questions(report, a_rows, c_rows):
    report.page("9. Control questions")
    best_a = min(a_rows, key=lambda r: r["wall_seconds"])
    best_c = min(c_rows, key=lambda r: r["wall_seconds"])
    report.qa(1, "Physical core versus logical processor",
              "A physical core is hardware that executes instructions. A logical processor "
              "is an OS scheduling context; simultaneous multithreading can expose more "
              "than one context per core. This machine reports 24 physical cores and 32 "
              "logical processors. Task 1a flattens around the top end of that range; "
              f"its recorded minimum is at {best_a['threads']} threads. Task 1c instead "
              f"stops improving near {best_c['threads']} consumers because its producer, "
              "rather than the available core count, limits delivery.")
    report.qa(2, "How are partition boundaries made correct?",
              "A worker with nonzero start examines byte start-1. If that byte is LF, "
              "start already begins a line. Otherwise the worker skips the rest of the "
              "partial line. It then counts complete lines whose starting position is "
              "strictly below end. A line crossing end belongs to the earlier worker; "
              "the following worker skips its remainder. No central thread reads the "
              "file on behalf of the workers. Exhaustive small-file boundary tests verify this.")
    report.qa(3, "How do unsynchronized counters lose updates?",
              "A reads 0; B reads 0; A computes and writes 1; B computes and writes 1. "
              "Two values were counted but the stored counter increased only once. The "
              "read/add/write sequence must be protected as a unit. The large unsafe "
              "runs use natural scheduling, while the separate two-thread barrier example "
              "forces exactly this order and produces 1 instead of 2.")
    report.qa(4, "Why are per-thread counters faster than a mutex?",
              "Private counters have no competing writers in the counting loop. Only "
              "three values per worker are merged after joining. A shared mutex permits "
              "one increment at a time and adds lock acquisition, wake-up, and cache "
              "ownership costs. Removing the GIL permits parallel execution; it does "
              "not remove contention introduced by the algorithm.")
    report.qa(5, "I/O-bound USB versus a server waiting on the network",
              "I/O-bound work spends its critical path waiting for external data. Many "
              "reads on one HDD compete for a shared spindle, head, controller, and link. "
              "Independent network requests can overlap remote waits and use different "
              "resources. Concurrency helps when independent waiting and unused capacity "
              "exist. The measured read/parse fractions determine whether this particular "
              "USB program is actually I/O-dominated; the mere presence of a USB drive does not.")
    report.qa(6, "Static partitions versus a queue",
              "Static partitioning assigns predictable work once and avoids a central "
              "handoff. It works well for similarly sized uniform tasks. A queue distributes "
              "work dynamically, balances uneven durations, and overlaps pipeline stages, "
              "but introduces communication and synchronization. A bounded queue limits "
              "backlog and provides backpressure. Here uniform file partitions scale "
              "better than a pipeline with one reader.")


def conclusion(report, a_rows, c_rows, local, usb, diagnosis):
    report.page("10. Conclusions and reproducibility")
    best_a = min(a_rows, key=lambda r: r["wall_seconds"])
    best_c = min(c_rows, key=lambda r: r["wall_seconds"])
    private = next(r for r in local if r["task"] == "1b"
                   and r["mode"] == "local" and r["threads"] == 32)
    report.p(f"On this machine, warm internal-file counting is predominantly CPU/parsing "
             f"work: Task 1a improves from {a_rows[0]['wall_seconds']:.3f} s at one thread "
             f"to {best_a['wall_seconds']:.3f} s at {best_a['threads']} threads. "
             "The gain approaches a plateau rather than continuing in proportion to "
             "thread count. Oversubscription is not a substitute for additional physical cores.")
    report.p(f"The producer-consumer implementation reaches its minimum at "
             f"{best_c['threads']} workers ({best_c['wall_seconds']:.3f} s); its single "
             "reader and queue become the limiting stage. Shared-counter experiments "
             "show that free threading does not ensure correctness or good scaling. "
             f"Private counters return the correct result in {private['wall_seconds']:.3f} s "
             "at 32 threads; the unsafe method loses updates and synchronization introduces a cost.")
    report.p(diagnosis)
    report.h("Limits of these measurements")
    report.p("This is one machine, one seeded dataset, one recorded campaign, a Balanced "
             "power plan, and a heterogeneous mobile CPU. Turbo behavior, thermal state, "
             "background work, filesystem readahead, and device-internal caching were not "
             "independently controlled. Most points have one observation, so small "
             "differences and universal thread-count recommendations are not justified. "
             "A flash stick may behave differently from the measured external HDD.")
    report.h("Reproduce and inspect")
    report.p("The repository README gives exact commands for generation, splitting, "
             "every task, tests, cold USB runs, and report rebuilding. The suite uses a "
             "fresh process per configuration. Each measurement records counters, timing, "
             "peak memory, runtime/GIL state, input hash, and counting-source hash. "
             "summary.csv provides the chart data. DEFENSE.md explains the key code paths.")
    report.h("References")
    references = [
        ("Assignment", "Laboratory Work 1: Concurrency in Practice, provided four-page handout."),
        ("Python free threading", "https://docs.python.org/3.14/howto/free-threading-python.html"),
        ("Blocking queue and shutdown", "https://docs.python.org/3.14/library/queue.html"),
        ("Compact integer arrays", "https://docs.python.org/3.14/library/array.html"),
        ("Windows peak working set", "https://learn.microsoft.com/en-us/windows/win32/api/psapi/ns-psapi-process_memory_counters"),
        ("USB connection version", "https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/usbioctl/ni-usbioctl-ioctl_usb_get_node_connection_information_ex_v2"),
    ]
    for name, target in references:
        if target.startswith("https:"):
            report.story.append(Paragraph(f'{escape(name)}: <link href="{target}" color="#1764a0">{escape(target)}</link>', report.small))
            report.markdown.append(f"- [{name}]({target})")
        else:
            report.p(f"{name}: {target}", small=True)


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(NAVY)
    canvas.rect(0, A4[1] - 13, A4[0], 13, fill=1, stroke=0)
    canvas.setStrokeColor(colors.HexColor("#d5dee6"))
    canvas.line(48, 34, A4[0] - 48, 34)
    canvas.setFillColor(GRAY)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(48, 21, "Rustem Cimendur | FAF-243 | Concurrency in Practice")
    canvas.drawRightString(A4[0] - 48, 21, str(doc.page))
    if doc.page > 1:
        canvas.setFont("Helvetica", 7.5)
        canvas.drawRightString(A4[0] - 48, A4[1] - 33, "NETWORK PROGRAMMING / LAB 1")
    canvas.restoreState()


def main():
    local, usb, reconnect, controls, data, hardware = load_evidence()
    if {r["role"] for r in controls} != {"additional_warm_control", "additional_storage_control"}:
        raise ValueError("Both matched-parser storage controls are required for this report.")
    a_rows = sorted([r for r in local if r["task"] == "1a"], key=lambda r: r["threads"])
    b_rows = [r for r in local if r["task"] == "1b"]
    c_rows = sorted([r for r in local if r["task"] == "1c"], key=lambda r: r["threads"])
    asset_dir = BASE / "output/figures"
    asset_dir.mkdir(parents=True, exist_ok=True)
    figures.setup()
    architecture_path = figures.architecture(asset_dir)
    a_figure = figures.scaling(a_rows, asset_dir, "1a")
    b_figure = figures.counter_comparison(b_rows, asset_dir)
    c_figure = figures.scaling(c_rows, asset_dir, "1c")
    usb_figure = figures.scaling(usb, asset_dir, "2")
    timeline = figures.usb_timeline(usb, asset_dir)
    cold = next(row for row in usb if row["threads"] == 1)
    control_figure = figures.storage_controls(cold, controls, asset_dir)
    test_log = (BASE / "results/tests.log").read_text(encoding="utf-8-sig")
    evidence_figure = figures.evidence(local, usb, data, test_log, asset_dir)
    report = Report()
    cover(report)
    environment(report, data, hardware)
    methods(report, architecture_path)
    task1a_page(report, a_rows, a_figure)
    task1b_page(report, b_rows, b_figure)
    task1c_page(report, c_rows, a_rows, c_figure)
    task2_page(report, usb, a_rows, reconnect, usb_figure)
    diagnosis = storage_diagnosis(report, usb, controls, timeline, control_figure)
    evidence_page(report, local, usb, data, evidence_figure)
    control_questions(report, a_rows, c_rows)
    conclusion(report, a_rows, c_rows, local, usb, diagnosis)
    pdf_dir = BASE / "output/pdf"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    pdf = pdf_dir / "lab1_report.pdf"
    doc = SimpleDocTemplate(str(pdf), pagesize=A4, rightMargin=48, leftMargin=48,
                            topMargin=51, bottomMargin=47,
                            title="Lab 1 - Concurrency in Practice", author="Rustem Cimendur",
                            subject="Network Programming laboratory work, FAF-243")
    doc.build(report.story, onFirstPage=footer, onLaterPages=footer)
    (BASE / "report.md").write_text("\n".join(report.markdown) + "\n", encoding="utf-8")
    keys = ["task", "mode", "threads", "repetition", "role", "wall_seconds",
            "cpu_seconds", "average_cpu_cores", "peak_memory_mib", "negative",
            "positive", "zero", "total", "correct", "speedup"]
    all_rows = local + usb + controls
    with (BASE / "results/summary.csv").open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=keys)
        writer.writeheader()
        for row in all_rows:
            baseline = next(r for r in all_rows if r["task"] == row["task"]
                            and r["mode"] == row["mode"] and r["threads"] == 1
                            and (r["role"] == row["role"] or row["task"] == "1b"))
            values = {key: row[key] for key in keys if key in row}
            values.update(row["counts"])
            values["speedup"] = baseline["wall_seconds"] / row["wall_seconds"]
            writer.writerow(values)
    lab.save_json(BASE / "results/validation_summary.json", {
        "dataset_count": data["count"], "reference_counts": data["counts"],
        "local_configurations": len(local), "cold_usb_configurations": len(usb),
        "additional_storage_controls": len(controls),
        "all_correct_methods_match": True,
        "unsafe_failures_observed": sum(not r["correct"] for r in b_rows),
        "usb_copies_verified": 8, "usb_reconnects_observed": 3,
        "all_measurements_gil_disabled": True,
        "source_sha256": lab.sha256_file(BASE / "lab.py"),
    })
    print(f"Created: {pdf}")
    print(f"Created editable report, summary.csv and {len(list(asset_dir.glob('*.png')))} figures.")


if __name__ == "__main__":
    main()
