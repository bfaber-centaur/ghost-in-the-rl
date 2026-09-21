# 00 — MiMo archive inventory

Generated offline from the captured archive; no dashboard requests.

- Manifest SHA-256: `c67bcb4716b0fa92ef0f290734d000a21618fe08f67b593ce33f640b221b1d90`
- Analyzer SHA-256: `f75fbd114089c34daed8f3866533d2a6706bdb20060383bc666cdef73f94d5c9`
- Capture window (UTC): 2026-09-21T05:28:55.787986Z to 2026-09-21T05:51:52.192622Z.
- 120 manifest entries: 109 successful, 11 failed requests.
- 97 unique objects; all referenced successful gzip bodies pass SHA-256 and byte-count checks.
- Unique bytes: 382,726 compressed / 1,442,687 decompressed.

## Coverage

| Run | Version | Catalog | Returned | With numeric values | Unique slots | Null slots | Conflicts |
|---|---|---:|---:|---:|---:|---:|---:|
| flash | `3-5513.32.6.28` | 2062 | 2062 | 2062 | 61,860 | 4,418 | 0 |
| pro | `3-5513.30.15.30` | 2029 | 2029 | 2029 | 60,870 | 5,208 | 0 |

Slots include nulls; repeated identical observations are counted once. Conflicting values are retained as variants.
Catalog coverage is checked against returned payload keys, independently of the collector's request counter.

- flash: missing tags 0; extra tags 0; empty arrays 0; all-null arrays 0; duplicate slots 0; catalog conflict False. Observed historical steps: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30].
  Nulls occur in 300 metrics. Null slots by namespace: partial=4418.
- pro: missing tags 0; extra tags 0; empty arrays 0; all-null arrays 0; duplicate slots 0; catalog conflict False. Observed historical steps: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30].
  Nulls occur in 295 metrics. Null slots by namespace: actor=144, critic=192, ctx_prompt_length=48, ctx_response_length=48, ctx_total_length=64, dynsam=48, env=16, partial=4536, train=112.
- Request/response tag discrepancies: 0.
- Shared exact tag names across groups: 2014.
- Tags exclusive to flash@3-5513.32.6.28: 48 (listed in inventory.json).
- Tags exclusive to pro@3-5513.30.15.30: 15 (listed in inventory.json).

## Metric taxonomy

Families are literal top-level namespaces. Dataset IDs are additionally normalized in `structural_pattern`; no mechanism is inferred from a label.

| Namespace | flash | pro |
|---|---:|---:|
| actor | 256 | 257 |
| critic | 324 | 324 |
| ctx_prompt_length | 81 | 81 |
| ctx_response_length | 81 | 81 |
| ctx_total_length | 108 | 108 |
| dynsam | 83 | 83 |
| env | 15 | 15 |
| partial | 385 | 337 |
| penalty | 521 | 535 |
| perf | 1 | 1 |
| timing_s | 3 | 3 |
| train | 191 | 191 |
| train_infer_diff | 11 | 11 |
| training | 2 | 2 |

## Timeline

Numeric source times interpreted as Unix seconds, consistent with capture dates and cross-endpoint values; timestamp field semantics are preserved, not assumed to be step start/end.

Timeline rows retain object hashes, manifest lines, JSON pointers, and capture times. Identical events combine source references. Untimed benchmarks sort after timed events; CSV row adjacency is not a causal assertion.

| Run | Start (UTC) | End (UTC) | Last completed step | Latest sampler step | Reported restarts | Restarts in latest status event list |
|---|---|---|---:|---:|---:|---:|
| flash | 2026-09-15T15:16:29.264000Z | 2026-09-19T02:22:09.264000Z | 30 | 31 | 5 | 4 |
| pro | 2026-09-15T10:32:19.334000Z | 2026-09-20T18:01:40.953000Z | 30 | 31 | 14 | 9 |

The latest snapshot is selected by capture time for this table only; all snapshots remain in inventory.json.
Differences between restart counters and event-list counts prevent a claim of complete restart reconstruction.

Step-coordinate comparisons (differences can reflect distinct attempts, not clock error):

- flash: steps with conflicting series wall timestamps []; status-step timestamp checks across captures: {'exact_match': 46, 'not_in_series': 4}.
- pro: steps with conflicting series wall timestamps []; status-step timestamp checks across captures: {'exact_match': 60}.

Status step occurrences absent from the retained series (deduplicated across captures):

| Run | Step | Earlier/status time (UTC) | Retained series time(s) (UTC) | Matching retained status redo flag(s) |
|---|---:|---|---|---|
| flash | 16 | 2026-09-16T22:24:59.226925Z | 2026-09-17T05:02:07.986262Z | True |
| flash | 17 | 2026-09-17T00:32:03.030891Z | 2026-09-17T07:15:25.081739Z | True |

These source distinctions are retained in timeline.csv; matching redo flags are publisher-supplied metadata.

### Publisher notices

- 2026-09-16T17:58:17.495634Z: we have updated the latest deepswe results for flash step 12 & pro step 8. we will keep posting as the offline evaluation results come out. (manifest line 2, `/notices/5`; structured run scope: null).
- 2026-09-16T20:08:00.378206Z: the mimo-v2.6-pro run is restarting due to a vram issue on one node. (manifest line 2, `/notices/4`; structured run scope: null).
- 2026-09-17T02:27:38.930446Z: we restarted the flash run from step 15. reason: a type of infra error on one of datasets was not correctly detected over the past ~3 hours. (manifest line 2, `/notices/3`; structured run scope: null).
- 2026-09-17T12:20:11.047444Z: there was a network connectivity issue between the pro training cluster and the grader deployment. we have restarted the run. we also removed the cyber dataset from the upcoming pro run, since we observed some bad patterns in the rollout logs. (manifest line 2, `/notices/2`; structured run scope: null).
- 2026-09-18T03:49:42.889267Z: the pro run restarted at step 17 due to a GPU OOM issue caused by expert load imbalance. we have adjusted the training parallelism strategy. (manifest line 2, `/notices/1`; structured run scope: null).
- 2026-09-19T10:14:26.861832Z: we filtered out tasks that are relatively easy for the current pro model. (manifest line 2, `/notices/0`; structured run scope: null).

## Interpretation boundary and next questions

This pass describes the public archive. Direct dataset/harness labels must stay separate from operational measurements in any later workload-classification evaluation.
The observed timing_s family, perf token count, and environment/sampler fields are candidate operational observables. Their availability alone does not identify an interconnect or TP/PP/DP strategy.
The parallelism-change notice is a publisher statement, not an independently identified configuration or precisely matched intervention.

Before hypotheses: inspect null patterns and cross-endpoint clock agreement; establish which quantities are measured, derived, or merely named; read the original SPAR proposal and map its required observables to the inventory.

## Limitations

- Completeness is relative to the captured catalog, not all internal training telemetry.
- Historical arrays retain a published view; status may preserve earlier attempts, but complete metrics for overwritten attempts cannot be reconstructed here.
- Null is retained as unknown/missing, never converted to zero.
- Status event lists are bounded snapshots, not a complete restart history.
- Notices are publisher claims; null run scopes are not silently assigned from prose.
- Benchmark rows have no source timestamp or version; neither is borrowed from training series.
- Live sampler entries are not completed training steps.
- Units remain unknown except explicitly supported timing fields.
