# 01 — Metric map

First-pass map of the public MiMo RL metric surface. Scope labels below are lexical hints derived from tag paths, not publisher-confirmed aggregation semantics.

- Manifest SHA-256: `c67bcb4716b0fa92ef0f290734d000a21618fe08f67b593ce33f640b221b1d90`
- Run/version groups: `flash@3-5513.32.6.28`, `pro@3-5513.30.15.30`
- Exact union: **2,077 tags**; shared by both groups: **2,014**
- Flash: **2,062** catalog tags / **2,062** returned series
- Pro: **2,029** catalog tags / **2,029** returned series

## Lexical scope reduction

The purpose of this split is triage: shrink ~2k tags to a human-sized surface without pretending a path name proves measurement semantics.

| Scope hint | Exact tags | Rule of thumb |
|---|---:|---|
| `dataset` | 1,108 | contains a literal `dataset-*` segment |
| `harness` | 434 | contains `harness` / `harness-*` but no dataset id |
| `partial-bucket` | 160 | `partial/...` path with a numeric bucket |
| `workload-aggregate` | 34 | contains agentic/chat/code/cyber/general/visual but no dataset id |
| `penalty-subsystem` | 239 | structured `penalty/...` path without dataset/harness id |
| `train-subsystem` | 24 | structured `train/...` path without dataset/harness id |
| `run-global-looking` | 78 | none of the above; candidate top-level/global surface |

### Namespace × scope

| Namespace | dataset | harness | partial-bucket | workload-aggregate | penalty-subsystem | train-subsystem | run-global-looking | Total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| actor | 225 | 0 | 0 | 9 | 0 | 0 | 23 | 257 |
| critic | 300 | 0 | 0 | 12 | 0 | 0 | 12 | 324 |
| ctx_prompt_length | 75 | 0 | 0 | 3 | 0 | 0 | 3 | 81 |
| ctx_response_length | 75 | 0 | 0 | 3 | 0 | 0 | 3 | 81 |
| ctx_total_length | 100 | 0 | 0 | 4 | 0 | 0 | 4 | 108 |
| dynsam | 75 | 0 | 0 | 1 | 0 | 0 | 7 | 83 |
| env | 10 | 0 | 0 | 1 | 0 | 0 | 4 | 15 |
| partial | 223 | 0 | 160 | 1 | 0 | 0 | 1 | 385 |
| penalty | 0 | 296 | 0 | 0 | 239 | 0 | 0 | 535 |
| perf | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 1 |
| timing_s | 0 | 0 | 0 | 0 | 0 | 0 | 3 | 3 |
| train | 25 | 138 | 0 | 0 | 0 | 24 | 4 | 191 |
| train_infer_diff | 0 | 0 | 0 | 0 | 0 | 0 | 11 | 11 |
| training | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 2 |

## Candidate panels for the next pass

These are names worth plotting first; inclusion is based on path position and obvious operational/RL labels, not a claim that the metric means exactly what its name suggests.

**Systems / cadence.** `perf/total_num_tokens`, `timing_s/outer_gen`, `timing_s/trainer_ops`, `timing_s/step`, `env/active`, `env/total_setup`, `env/total_error`, `env/possible_leak`, `partial/avg_staleness`, `train/trace/records`, `train/trace/files`, `train/trace/drain_wait_seconds`, `train/trace/late_finishes`, `train/trace/failed_writes`.

**Sampler / curriculum.** `dynsam/avg@n`, `dynsam/num_measurable`, `dynsam/num_target`, `dynsam/passrate/one`, `dynsam/passrate/zero`, `dynsam/infra_error/seq_rate`.

**RL optimization.** `actor/entropy_loss`, `actor/grad_norm`, `actor/pg_loss`, `actor/pg_clipfrac`, `actor/ppo_kl`, `critic/rewards/mean`, `critic/advantages/mean`, `critic/returns/mean`, `train/passrate/avg_passrate`, `train/passrate/passrate_0_ratio`, `train/passrate/passrate_1_ratio`.

**Length / workload shape.** `ctx_prompt_length/mean`, `ctx_response_length/mean`, `ctx_total_length/mean`, `ctx_total_length/clip_ratio`.

**Train ↔ inference consistency.** `train_infer_diff/new_infer/kl`, `train_infer_diff/new_infer/diff_abs_mean`, `train_infer_diff/nll_loss/log_probs`, `train_infer_diff/nll_loss/rollout_log_probs`.

## First trace-level observations

These are smoke-test observations to motivate plots. They are deliberately phrased as discontinuities/relationships, not causes.

- `pro`: `timing_s/step` is almost exactly `outer_gen + trainer_ops + residual`: Pearson r=0.999987; residual mean 227.4s (range 166.0–313.4s).
- `flash`: the same relationship has Pearson r=0.999860; residual mean 223.9s (range 151.3–320.3s).
- Retained step 16→17: Pro `train/trace/records` 1,632,230→3,268,260 (**+100.2%**); Flash 1,642,520→1,617,590 (**−1.5%**). This is a candidate Pro-specific discontinuity.
- The same boundary changes Pro `timing_s/trainer_ops` 3,822.20s→6,353.58s (**+66.2%**); Flash 3,091.39s→3,475.79s (**+12.4%**). Alignment with notices/interventions should be tested separately.
- Pro `actor/grad_norm` has a sharp maximum at step 19: **0.0335148**. That is an anomaly candidate, not yet an explained event.
- Pro `env/possible_leak` is nonzero at least once; maximum **207** at step 25. The label is publisher-supplied and should not be semantically expanded without source evidence.

## Run-specific catalog differences

- Pro-only: 15 tags. These are mostly stage-credit diagnostics plus `actor/num_zeros_in_grad_encoders`.
- Flash-only: 48 tags. Differences are dominated by extra `partial` buckets 8/9 and a handful of dataset/bucket combinations.
- Treat these as schema/configuration differences until proven otherwise.

## Interpretation boundary

- `scope_hint` is computed from literal path segments only. `run-global-looking` means “no explicit dataset/harness/bucket/workload scope in the tag”, not guaranteed global aggregation.
- Dataset IDs and harness IDs are preserved in the generated CSV; normalized `structural_pattern` is for grouping only.
- Correlation and jump statistics are descriptive over the 30 retained historical coordinates. Restarted/overwritten attempts are not recovered by this map.
- No tag name is treated as proof of network traffic, collective communication, parallelism strategy, or causal mechanism.

The analyzer emits `metric-map.csv` for the full union and `metric-shortlist.csv` for the 102 `run-global-looking` + `train-subsystem` rows. These are reproducible generated inspection artifacts rather than hand-maintained taxonomy.

Next pass: plot the candidate panels against the source-backed timeline, with restart/notices as annotations and Pro/Flash shown side by side.
