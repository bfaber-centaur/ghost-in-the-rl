# DEVLOG

Append-only notes from the project. New entries go at the top of the dated log; old entries are not rewritten to make later understanding look cleaner than it was at the time.

## 2026-09-20 — First MiMo archive

- Found Xiaomi's public MiMo-V2.6 RL dashboard and started by treating the browser as a probe rather than assuming an API.
- The reconnaissance recorder exposed ordinary JSON endpoints for runs, status, live sampler state, notices, benchmarks, metric tags, and historical series.
- Replaced the browser probe with a small stdlib-only Go collector using content-addressed, gzip-compressed objects plus an NDJSON manifest.
- The first Pro backfill hit a 502 after roughly 1,700 metrics. Hardened the collector with retry/backoff, manifest-aware resume, and recursive splitting of failing `/series` batches.
- Completed the historical backfill: **Pro 2,029/2,029 metrics; Flash 2,062/2,062 metrics**.
- Preserved the final live sampler state separately from completed historical series; both runs ended at completed step 30 while the live endpoint retained partial step-31 state.
- Next: inventory the captured metric families, freeze a clean analysis snapshot, and compare what this real telemetry exposes against assumptions from the earlier SPAR interconnect/workload-classification proposal.
