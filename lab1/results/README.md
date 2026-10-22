# Measurement evidence

These files contain actual executions on the recorded machine. They are not sample
results. Large text inputs remain in the ignored `lab1/data/` directory.

| Material | What it establishes |
| --- | --- |
| `numbers.manifest.json`, `generation.log` | Seed, complete input size, reference sign counts, and SHA-256 |
| `parts.manifest.json`, `split.log` | Eight consecutive 6,250,000-value files; source-order hash verification |
| `usb_copy_verification.json` | All eight files copied to the USB disk with matching SHA-256, before reconnects |
| `hardware.json`, `runtime.json` | Hardware, Windows build, free-threaded interpreter, and disabled GIL |
| `usb_connection.json` | Actual USB descriptor and SuperSpeed connection flags from read-only hub queries |
| `tests.log` | All 13 correctness tests passed |
| `local_suite.log` | Original progress/output for all 22 local configurations |
| `local/*.json`, `local/*.log` | Per-run measurements, individual counters, source/input hashes, and exact child commands |
| `usb_campaign.log`, `usb/reconnect_*.json` | Drive-letter disappearance and reappearance before each cold USB run |
| `usb/task2_*.json`, `usb/task2_*.log` | Three required cold USB runs, including individual file read/parse intervals |
| `controls/` | Separately labeled matched-parser NVMe and warm USB diagnostics |
| `summary.csv` | Chart data, method-specific speed-up, and correctness for every timed run |
| `validation_summary.json` | Report-time consistency checks across hashes, counters, runtime state, and reconnect records |

The three 32-thread unsafe counter runs are intentionally retained with
`correct: false`. They demonstrate lost updates and must not be treated as accepted
counting solutions. All synchronized/private methods and USB runs must match all
three reference counters and sum to 50,000,000.

`peak_memory_mib` is the fresh process's lifetime peak resident working set,
including untimed input loading where applicable. `preload_seconds_excluded` is
not part of `wall_seconds`. CPU seconds divided by wall seconds estimates average
CPU-core usage, not percentage of the entire 32-processor system.

The USB observer checks only the drive-letter bitmask, never the data files. Its
records corroborate removal/reconnection; safe ejection and physical unplugging
were performed by the user. The report's evidence image is explicitly labeled as
a rendering of these records, rather than a desktop screenshot.
