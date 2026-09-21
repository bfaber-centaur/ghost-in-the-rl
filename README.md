# ghost-in-the-rl

Watching public RL training runs while they are still messy.

This repo archives and analyzes telemetry exposed by Xiaomi's public MiMo-V2.6 RL dashboard. The rule is simple: **preserve first, interpret second**. Keep the raw traces intact, then ask what an outside observer can actually infer from operational telemetry.

Current pieces:

- `mimo-capture-go/` — direct API collector and resumable historical backfill
- `py-mimi-cap/` — original browser reconnaissance recorder
- `DEVLOG.md` — append-only research and development log
- `analysis/` — offline archive inventory, metric taxonomy, and source-backed timeline

The first complete capture includes **2,029/2,029 Pro metrics** and **2,062/2,062 Flash metrics**, plus run status, notices, benchmarks, and final live sampler state.

Raw capture data is intentionally ignored by git.

See [the first inventory](analysis/00-inventory.md) and
[reproduction instructions](analysis/README.md). Generated summaries are tracked;
the analyzer reads the original archive without network access or input writes.
