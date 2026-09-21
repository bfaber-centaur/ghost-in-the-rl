# DEVLOG

Append-only notes from the project. New entries go at the top of the dated log; old entries are not rewritten to make later understanding look cleaner than it was at the time.


## 2026-09-21 (UTC) — First metric map

- Added an offline metric-map analyzer that reduces the exact 2,077-tag union using literal path structure before assigning any semantics.
- First lexical cut: 1,108 dataset-scoped tags, 434 harness-scoped, 160 partial buckets, 34 workload aggregates, 239 penalty-subsystem, 24 train-subsystem, and 78 run-global-looking tags.
- Defined candidate panels for systems/cadence, sampler/curriculum, RL optimization, workload shape, and train↔inference consistency.
- Found a Pro-specific retained step-16→17 discontinuity worth plotting: `train/trace/records` +100.2% and `timing_s/trainer_ops` +66.2%, versus -1.5% and +12.4% on Flash. This is recorded as a discontinuity, not attributed to the nearby restart/parallelism notice.
- Next: align candidate traces with the source-backed event timeline and inspect intervention-adjacent windows. No causal or workload/interconnect classification claim yet.

## 2026-09-21 (UTC) — Offline inventory and timeline

- Added a standard-library Python analyzer that verifies captured object hashes/lengths, checks returned metric coverage independently of requested tags, and emits the four inventory/timeline artifacts under `analysis/`.
- Verified 120 manifest entries, including 109 successful responses and 11 failed requests; 97 unique successful objects passed integrity checks.
- Confirmed actual returned coverage: Pro 2,029/2,029 and Flash 2,062/2,062; no empty or entirely null series. Historical coordinates span steps 1–30; final live sampler state is step 31.
- Cataloged 14 literal namespaces per run, 2,014 shared tag names, 15 Pro-only tags, and 48 Flash-only tags. Preserved nulls: 5,208 Pro slots and 4,418 Flash slots, without imputing values or causes.
- Kept status, series, notices, and live records distinct. Flash status preserves earlier step-16/17 occurrences as well as later `redo: true` occurrences; historical series match the latter. The bounded status lists include fewer restart events than cumulative restart counters report.
- Kept this pass descriptive. Next: inspect missingness and measurement semantics, then read the original SPAR proposal and map its required observables to what is actually exposed. No workload/interconnect classifier or causal claim yet.

## 2026-09-20 — First MiMo archive

- Found Xiaomi's public MiMo-V2.6 RL dashboard and started by treating the browser as a probe rather than assuming an API.
- The reconnaissance recorder exposed ordinary JSON endpoints for runs, status, live sampler state, notices, benchmarks, metric tags, and historical series.
- Replaced the browser probe with a small stdlib-only Go collector using content-addressed, gzip-compressed objects plus an NDJSON manifest.
- The first Pro backfill hit a 502 after roughly 1,700 metrics. Hardened the collector with retry/backoff, manifest-aware resume, and recursive splitting of failing `/series` batches.
- Completed the historical backfill: **Pro 2,029/2,029 metrics; Flash 2,062/2,062 metrics**.
- Preserved the final live sampler state separately from completed historical series; both runs ended at completed step 30 while the live endpoint retained partial step-31 state.
- Next: inventory the captured metric families, freeze a clean analysis snapshot, and compare what this real telemetry exposes against assumptions from the earlier SPAR interconnect/workload-classification proposal.
