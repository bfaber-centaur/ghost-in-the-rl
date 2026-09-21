#!/usr/bin/env python3
"""Build a lexical/trace metric map for the captured MiMo RL archive.

This pass is intentionally conservative: path structure is used to create scope
hints, not semantic ground truth. Raw values are summarized only to make the
human-sized surface easier to inspect before hypothesis testing.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

WORKLOAD_LABELS = {"agentic", "chat", "code", "cyber", "general", "visual"}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--archive", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    return p.parse_args()


def load_manifest(root: Path) -> list[dict]:
    path = root / "manifest.ndjson"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def load_object(root: Path, entry: dict) -> dict:
    with gzip.open(root / entry["object"], "rt", encoding="utf-8") as f:
        return json.load(f)


def structural_pattern(tag: str) -> str:
    parts = tag.split("/")
    out = []
    for i, part in enumerate(parts):
        if part.startswith("dataset-"):
            out.append("{dataset}")
        elif part.startswith("harness-"):
            out.append("{harness}")
        elif parts[0] == "partial" and i > 0 and part.isdigit():
            out.append("{bucket}")
        else:
            out.append(part)
    return "/".join(out)


def tag_features(tag: str) -> dict:
    parts = tag.split("/")
    dataset = next((p for p in parts if p.startswith("dataset-")), "")
    harness = next((p for p in parts if p.startswith("harness-")), "")
    workload = next((p for p in parts[1:] if p in WORKLOAD_LABELS), "")
    bucket = next((p for p in parts[1:] if p.isdigit()), "")
    ns = parts[0]

    if dataset:
        scope = "dataset"
    elif harness or "harness" in parts:
        scope = "harness"
    elif ns == "partial" and bucket:
        scope = "partial-bucket"
    elif workload:
        scope = "workload-aggregate"
    elif ns == "penalty" and len(parts) >= 3:
        scope = "penalty-subsystem"
    elif ns == "train" and len(parts) >= 3:
        scope = "train-subsystem"
    else:
        scope = "run-global-looking"

    return {
        "namespace": ns,
        "depth": len(parts),
        "structural_pattern": structural_pattern(tag),
        "scope_hint": scope,
        "workload_label": workload,
        "dataset_id": dataset,
        "harness_id": harness,
        "numeric_bucket": bucket,
    }


def summarize(values: list) -> dict:
    nonnull = [float(v) for v in values if v is not None]
    out = {
        "nonnull": len(nonnull),
        "null": len(values) - len(nonnull),
        "first": "",
        "last": "",
        "min": "",
        "max": "",
        "mean": "",
        "std": "",
        "constant": "",
        "largest_abs_jump": "",
        "largest_abs_jump_step": "",
    }
    if not nonnull:
        return out
    out.update(
        first=nonnull[0],
        last=nonnull[-1],
        min=min(nonnull),
        max=max(nonnull),
        mean=statistics.fmean(nonnull),
        std=statistics.pstdev(nonnull) if len(nonnull) > 1 else 0.0,
        constant=(max(nonnull) == min(nonnull)),
    )
    best = None
    for i in range(1, len(values)):
        a, b = values[i - 1], values[i]
        if a is None or b is None:
            continue
        jump = abs(float(b) - float(a))
        if best is None or jump > best[0]:
            best = (jump, i + 1)
    if best:
        out["largest_abs_jump"], out["largest_abs_jump_step"] = best
    return out


def pearson(a: list, b: list) -> str | float:
    pairs = [(float(x), float(y)) for x, y in zip(a, b) if x is not None and y is not None]
    if len(pairs) < 2:
        return ""
    xs = [x for x, _ in pairs]
    ys = [y for _, y in pairs]
    if max(xs) == min(xs) or max(ys) == min(ys):
        return ""
    return statistics.correlation(xs, ys)


def pct(a: float, b: float) -> float | None:
    if a == 0:
        return None
    return (b - a) / abs(a) * 100.0


def fmt_pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v:+.1f}%"


def main() -> int:
    args = parse_args()
    root = args.archive.resolve()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)

    manifest_path = root / "manifest.ndjson"
    manifest_bytes = manifest_path.read_bytes()
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    manifest = load_manifest(root)

    catalogs: dict[tuple[str, str], set[str]] = {}
    series: dict[tuple[str, str], dict[str, list]] = defaultdict(dict)
    steps: dict[tuple[str, str], list] = {}

    for entry in manifest:
        if entry.get("status") != 200 or "object" not in entry:
            continue
        endpoint = entry.get("endpoint")
        if endpoint == "tags":
            body = load_object(root, entry)
            key = (body["run"], body["version"])
            current = set(body["tags"])
            if key in catalogs and catalogs[key] != current:
                raise SystemExit(f"catalog changed within capture for {key}")
            catalogs[key] = current
        elif endpoint == "series":
            body = load_object(root, entry)
            key = (body["run"], body["version"])
            if key in steps and steps[key] != body["steps"]:
                raise SystemExit(f"step grid changed across series batches for {key}")
            steps[key] = body["steps"]
            for tag, values in body["series"].items():
                old = series[key].get(tag)
                if old is not None and old != values:
                    raise SystemExit(f"conflicting series for {key} {tag}")
                series[key][tag] = values

    if not catalogs:
        raise SystemExit("no tag catalogs found")
    if set(catalogs) != set(series):
        raise SystemExit("catalog/series run-version sets differ")

    keys = sorted(catalogs)
    all_tags = sorted(set().union(*catalogs.values()))
    rows = []
    for tag in all_tags:
        f = tag_features(tag)
        row = {"tag": tag, **f}
        present_values = {}
        for run, version in keys:
            prefix = run
            present = tag in catalogs[(run, version)]
            row[f"{prefix}_present"] = present
            if present:
                vals = series[(run, version)][tag]
                present_values[run] = vals
                s = summarize(vals)
            else:
                s = {k: "" for k in summarize([])}
            for name, value in s.items():
                row[f"{prefix}_{name}"] = value
        if len(keys) == 2:
            r0, r1 = keys[0][0], keys[1][0]
            if r0 in present_values and r1 in present_values:
                row["cross_run_pearson"] = pearson(present_values[r0], present_values[r1])
            else:
                row["cross_run_pearson"] = ""
        rows.append(row)

    csv_path = out / "metric-map.csv"
    fieldnames = list(rows[0].keys())
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    union_count = len(all_tags)
    shared = sum(all(tag in catalogs[k] for k in keys) for tag in all_tags)
    scope_counts = Counter(r["scope_hint"] for r in rows)
    namespace_scope = defaultdict(Counter)
    for r in rows:
        namespace_scope[r["namespace"]][r["scope_hint"]] += 1

    md = []
    md.append("# 01 — Metric map\n")
    md.append("First-pass map of the public MiMo RL metric surface. Scope labels below are lexical hints derived from tag paths, not publisher-confirmed aggregation semantics.\n")
    md.append(f"- Manifest SHA-256: `{manifest_sha}`")
    md.append(f"- Run/version groups: {', '.join(f'`{r}@{v}`' for r, v in keys)}")
    md.append(f"- Exact union: **{union_count:,} tags**; shared by all groups: **{shared:,}**")
    for run, version in keys:
        md.append(f"- {run}: **{len(catalogs[(run, version)]):,}** catalog tags / **{len(series[(run, version)]):,}** returned series")

    md.append("\n## Lexical scope reduction\n")
    md.append("The purpose of this split is triage: shrink ~2k tags to a human-sized surface without pretending a path name proves measurement semantics.\n")
    md.append("| Scope hint | Exact tags | Rule of thumb |")
    md.append("|---|---:|---|")
    descriptions = {
        "dataset": "contains a literal `dataset-*` segment",
        "harness": "contains `harness` / `harness-*` but no dataset id",
        "partial-bucket": "`partial/...` path with a numeric bucket",
        "workload-aggregate": "contains agentic/chat/code/cyber/general/visual but no dataset id",
        "penalty-subsystem": "structured `penalty/...` path without dataset/harness id",
        "train-subsystem": "structured `train/...` path without dataset/harness id",
        "run-global-looking": "none of the above; candidate top-level/global surface",
    }
    order = ["dataset", "harness", "partial-bucket", "workload-aggregate", "penalty-subsystem", "train-subsystem", "run-global-looking"]
    for scope in order:
        md.append(f"| `{scope}` | {scope_counts[scope]:,} | {descriptions[scope]} |")

    md.append("\n### Namespace × scope\n")
    scopes_present = [s for s in order if scope_counts[s]]
    md.append("| Namespace | " + " | ".join(scopes_present) + " | Total |")
    md.append("|---|" + "---:|" * (len(scopes_present) + 1))
    for ns in sorted(namespace_scope):
        total = sum(namespace_scope[ns].values())
        md.append("| " + ns + " | " + " | ".join(str(namespace_scope[ns].get(s, 0)) for s in scopes_present) + f" | {total} |")

    md.append("\n## Candidate panels for the next pass\n")
    md.append("These are names worth plotting first; inclusion is based on path position and obvious operational/RL labels, not a claim that the metric means exactly what its name suggests.\n")
    panels = {
        "Systems / cadence": [
            "perf/total_num_tokens", "timing_s/outer_gen", "timing_s/trainer_ops", "timing_s/step",
            "env/active", "env/total_setup", "env/total_error", "env/possible_leak", "partial/avg_staleness",
            "train/trace/records", "train/trace/files", "train/trace/drain_wait_seconds",
            "train/trace/late_finishes", "train/trace/failed_writes",
        ],
        "Sampler / curriculum": [
            "dynsam/avg@n", "dynsam/num_measurable", "dynsam/num_target", "dynsam/passrate/one",
            "dynsam/passrate/zero", "dynsam/infra_error/seq_rate",
        ],
        "RL optimization": [
            "actor/entropy_loss", "actor/grad_norm", "actor/pg_loss", "actor/pg_clipfrac", "actor/ppo_kl",
            "critic/rewards/mean", "critic/advantages/mean", "critic/returns/mean",
            "train/passrate/avg_passrate", "train/passrate/passrate_0_ratio", "train/passrate/passrate_1_ratio",
        ],
        "Length / workload shape": [
            "ctx_prompt_length/mean", "ctx_response_length/mean", "ctx_total_length/mean", "ctx_total_length/clip_ratio",
        ],
        "Train ↔ inference consistency": [
            "train_infer_diff/new_infer/kl", "train_infer_diff/new_infer/diff_abs_mean",
            "train_infer_diff/nll_loss/log_probs", "train_infer_diff/nll_loss/rollout_log_probs",
        ],
    }
    for name, names in panels.items():
        md.append(f"\n**{name}.** " + ", ".join(f"`{n}`" for n in names if n in all_tags) + ".")

    md.append("\n## First trace-level observations\n")
    md.append("These are smoke-test observations to motivate plots. They are deliberately phrased as discontinuities/relationships, not causes.\n")

    by_run = {run: series[(run, version)] for run, version in keys}
    if "pro" in by_run and "flash" in by_run:
        for run in ("pro", "flash"):
            step_v = by_run[run]["timing_s/step"]
            outer_v = by_run[run]["timing_s/outer_gen"]
            trainer_v = by_run[run]["timing_s/trainer_ops"]
            residual = [s - o - t for s, o, t in zip(step_v, outer_v, trainer_v)]
            corr = statistics.correlation(step_v, [o + t for o, t in zip(outer_v, trainer_v)])
            md.append(
                f"- `{run}`: `timing_s/step` is almost exactly `outer_gen + trainer_ops + residual`: "
                f"Pearson r={corr:.6f}; residual mean {statistics.fmean(residual):.1f}s "
                f"(range {min(residual):.1f}–{max(residual):.1f}s)."
            )

        def step_pair(run: str, tag: str, before: int, after: int):
            vals = by_run[run][tag]
            return float(vals[before - 1]), float(vals[after - 1])

        p16, p17 = step_pair("pro", "train/trace/records", 16, 17)
        f16, f17 = step_pair("flash", "train/trace/records", 16, 17)
        md.append(
            f"- Retained step 16→17: Pro `train/trace/records` {p16:,.0f}→{p17:,.0f} ({fmt_pct(pct(p16,p17))}); "
            f"Flash {f16:,.0f}→{f17:,.0f} ({fmt_pct(pct(f16,f17))}). This is a candidate Pro-specific discontinuity."
        )
        p16, p17 = step_pair("pro", "timing_s/trainer_ops", 16, 17)
        f16, f17 = step_pair("flash", "timing_s/trainer_ops", 16, 17)
        md.append(
            f"- The same boundary changes Pro `timing_s/trainer_ops` {p16:,.2f}s→{p17:,.2f}s ({fmt_pct(pct(p16,p17))}); "
            f"Flash {f16:,.2f}s→{f17:,.2f}s ({fmt_pct(pct(f16,f17))}). Alignment with notices/interventions should be tested separately."
        )
        pgrad = by_run["pro"]["actor/grad_norm"]
        max_grad = max(v for v in pgrad if v is not None)
        max_grad_step = pgrad.index(max_grad) + 1
        md.append(f"- Pro `actor/grad_norm` has a sharp maximum at step {max_grad_step}: {max_grad:.7g}. That is an anomaly candidate, not yet an explained event.")
        pleak = by_run["pro"]["env/possible_leak"]
        if max(v for v in pleak if v is not None) > 0:
            m = max(v for v in pleak if v is not None)
            s = pleak.index(m) + 1
            md.append(f"- Pro `env/possible_leak` is nonzero at least once; maximum {m:g} at step {s}. The label is publisher-supplied and should not be semantically expanded without source evidence.")

    md.append("\n## Run-specific catalog differences\n")
    if len(keys) == 2:
        a, b = keys
        a_only = sorted(catalogs[a] - catalogs[b])
        b_only = sorted(catalogs[b] - catalogs[a])
        md.append(f"- `{a[0]}`-only: {len(a_only)} tags. " + (", ".join(f"`{x}`" for x in a_only[:8]) + (" …" if len(a_only) > 8 else "")))
        md.append(f"- `{b[0]}`-only: {len(b_only)} tags. " + (", ".join(f"`{x}`" for x in b_only[:8]) + (" …" if len(b_only) > 8 else "")))
        md.append("- Flash-only differences are dominated by extra `partial` buckets 8/9 and a handful of dataset/bucket combinations; Pro-only differences are mostly stage-credit diagnostics plus one encoder gradient-zero counter. Treat these as schema/configuration differences until proven otherwise.")

    md.append("\n## Interpretation boundary\n")
    md.append("- `scope_hint` is computed from literal path segments only. `run-global-looking` means “no explicit dataset/harness/bucket/workload scope in the tag”, not guaranteed global aggregation.")
    md.append("- Dataset IDs and harness IDs are preserved in the CSV; normalized `structural_pattern` is for grouping only.")
    md.append("- Correlation and jump statistics are descriptive over the 30 retained historical coordinates. Restarted/overwritten attempts are not recovered by this map.")
    md.append("- No tag name is treated as proof of network traffic, collective communication, parallelism strategy, or causal mechanism.")
    md.append("\nNext pass: plot the candidate panels against the source-backed timeline, with restart/notices as annotations and Pro/Flash shown side by side.\n")

    (out / "01-metric-map.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
