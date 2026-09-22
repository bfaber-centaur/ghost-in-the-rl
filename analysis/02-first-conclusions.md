# 02 — First conclusions from the MiMo metric map

A short interpretation pass over the two 30-step public runs. The [inventory](00-inventory.md) and [metric map](01-metric-map.md) establish capture coverage and candidate metrics. The pass-rate observations below come from a local extraction of the raw archive discussed on 2026-09-22; the per-step values and benchmark plots are **not yet committed as reproducible analysis outputs**.

## What we can see

1. **The in-house coding benchmark rises overall; Pro has a local slump.** The dashboard's `avg@3` plot ends at 65.43 for Pro and 62.87 for Flash. Pro dips near steps 15–16 and recovers afterward; Flash rises more steadily. Benchmark records in the archive have no source event timestamps or versions, so the visual step alignment is useful for generating questions, not for dating an intervention or attributing the recovery. The publisher reports restarts and later changes to parallelism and task filtering, but the graph alone cannot assign an effect to any one of them.

2. **Sampler and trainer pass rates must be read separately.** In the local 60-row extraction, Flash `dynsam/avg@n` rises from 0.514 to 0.644 and `train/passrate/avg_passrate` from 0.504 to 0.603. Pro's sampler average rises from 0.565 to 0.633, but its trainer average oscillates: 0.585 at step 14, 0.556 at 15, 0.584 at 16, 0.562 at 17. Thus a benchmark recovery does not imply monotone improvement on the trainer's measured population. Differences in prompt selection, weights, and timing remain possible explanations.

3. **The denominators and ratio series are the most informative anomaly.** `dynsam/num_measurable` varies from 1,636 to 4,728 in Pro while `dynsam/num_target` is 1,568. Flash's measurable count also varies and often exceeds target. The `train/passrate/passrate_0_ratio` and `passrate_1_ratio` rise remarkably smoothly over many steps, then both reset in Pro at steps 15 and 23; the sampler's zero/one ratios do not follow the same shape. Restart boundaries are consistent with those resets, but do not establish their mechanism. Do **not** subtract sampler and trainer zero/one ratios to estimate a common “middle” population until both populations and aggregation windows are verified.

4. **A Pro-specific operational discontinuity is real, but its meaning is open.** The committed [metric map](01-metric-map.md) reports Pro `train/trace/records` doubling from 1,632,230 to 3,268,260 across retained steps 16→17 while `timing_s/trainer_ops` increases 66.2%; Flash's record count is roughly flat at that boundary. `records` is not established to mean training passes, unique problems, or rollouts. The notice about an OOM restart and parallelism adjustment is a publisher statement, not proof of what caused this paired jump.

## Current map

| Observed | Interesting because | Current hypotheses | Missing knowledge | Discriminating next look |
|---|---|---|---|---|
| Measurable prompt count differs from target; trainer ratios ramp and reset | An apparently simple pass-rate comparison could change meaning with the denominator or aggregation window | Refilling and filtering change the sampled population; trainer ratios may use a different window or logging path | Exact live definitions of `num_measurable`, `avg@n`, and trainer zero/one ratios | Extract per-step dataset-level counts and ratios around Pro steps 14–17 and 22–24; check whether resets occur in every dataset simultaneously |

The released [MiMo `verl` replay buffer](https://github.com/XiaomiMiMo/verl/blob/mimo-oss/verl/trainer/ppo/v1/replay_buffer.py) filters prompt groups and refills a batch, giving a concrete reason to inspect selection. Its [metric utilities](https://github.com/XiaomiMiMo/verl/blob/mimo-oss/verl/trainer/ppo/metric_utils.py) provide a useful model of per-prompt pass rates, but are **not confirmed to be the producer of these dashboard series**. If the local extraction is promoted to a committed artifact, include the exact tag paths, run/version IDs, archive manifest hash, and extraction code so the numeric claims can be independently checked.
