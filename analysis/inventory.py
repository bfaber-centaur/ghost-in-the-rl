#!/usr/bin/env python3
"""Offline inventory for the archived MiMo dashboard schema (Python >= 3.10)."""
import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from urllib.parse import parse_qs, urlparse


class ArchiveError(ValueError):
    pass


def require(ok, message):
    if not ok:
        raise ArchiveError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(value).hexdigest()


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def integer(value):
    return type(value) is int and value >= 0


def utc(value):
    # Explicit interpretation, not proof of what an event timestamp measures.
    if value is None:
        return ""
    require(number(value), f"invalid source timestamp {value!r}")
    return datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")


def pointer(value):
    return str(value).replace("~", "~0").replace("/", "~1")


def source(event, line, path=""):
    return {"manifest_line": line, "object_sha256": event["sha256"],
            "json_pointer": path, "captured_at": event["captured_at"]}


def schema_paths(value, path="", found=None):
    """Types at structural paths; dynamic tag/result/dataset keys are collapsed."""
    if found is None:
        found = defaultdict(set)
    found[path or "/"].add(type(value).__name__)
    if isinstance(value, dict):
        dynamic = path == "/series" or path.endswith(("/ds", "/results/*"))
        for key, child in value.items():
            schema_paths(child, path + "/" + ("*" if dynamic else pointer(key)), found)
    elif isinstance(value, list):
        for child in value:
            schema_paths(child, path + "/*", found)
    return found


def load_archive(root):
    root = Path(root).resolve()
    manifest = root / "manifest.ndjson"
    frozen = manifest.read_bytes()
    records, failures, objects = [], [], {}
    endpoints = Counter()
    for line, raw in enumerate(frozen.splitlines(), 1):
        if not raw.strip():
            continue
        try:
            event = json.loads(raw)
            require(isinstance(event, dict), "manifest entry must be an object")
            require(isinstance(event.get("endpoint"), str), "missing endpoint")
            captured = datetime.fromisoformat(event["captured_at"].replace("Z", "+00:00"))
            require(captured.tzinfo is not None, "capture timestamp lacks timezone")
            endpoints[event["endpoint"]] += 1
            if not 200 <= event.get("status", 0) < 300 or event.get("error"):
                failures.append({"manifest_line": line, "endpoint": event["endpoint"],
                                 "run": event.get("run", ""), "status": event.get("status", 0)})
                continue
            path = (root / event["object"]).resolve()
            require(path.is_relative_to(root), "object path escapes archive")
            body = gzip.decompress(path.read_bytes())
            require(digest(body) == event["sha256"], "object SHA-256 mismatch")
            require(len(body) == event["bytes"], "object byte count mismatch")
            data = json.loads(body)
            require(isinstance(data, dict), "endpoint response must be an object")
            # Nonstandard JSON NaN/Infinity is an error, not a numeric observation.
            canonical(data)
            objects[event["sha256"]] = {"bytes": len(body), "compressed_bytes": path.stat().st_size}
            records.append((line, event, data))
        except (ValueError, KeyError, TypeError, OSError, EOFError, OverflowError) as exc:
            raise ArchiveError(f"manifest line {line}: {exc}") from exc
    require(records, "no successful objects")
    return manifest, frozen, records, failures, objects, endpoints


def analyze(root):
    manifest, frozen, records, failures, objects, endpoints = load_archive(root)
    catalogs = defaultdict(list)
    requested = defaultdict(set)
    returned = defaultdict(set)
    metrics = {}
    grids = defaultdict(lambda: defaultdict(set))
    statuses = defaultdict(list)
    live = defaultdict(list)
    descriptions = defaultdict(list)
    schemas = defaultdict(lambda: defaultdict(set))
    timeline = {}
    observations = []
    batch_discrepancies = []

    def event_row(event, line, path, run, version, kind, step=None, time=None,
                  state="", details=None):
        row = dict(run=run or "", version=version or "", event_kind=kind,
                   step=step, source_time_raw=time, source_time_utc=utc(time),
                   time_basis="Unix seconds interpretation" if time is not None else "not supplied",
                   completion_state=state, details=details or {})
        key = canonical(row)
        if key not in timeline:
            timeline[key] = dict(row, sources=[])
        ref = source(event, line, path)
        if ref not in timeline[key]["sources"]:
            timeline[key]["sources"].append(ref)

    for line, event, data in records:
        endpoint = event["endpoint"]
        for path, types in schema_paths(data).items():
            schemas[endpoint][path].update(types)
        run, version = event.get("run", ""), event.get("version", "")
        try:
            require(endpoint in {"runs", "notices", "benchmarks", "status", "live", "tags", "series", "series-pins"},
                    f"unrecognized endpoint {endpoint!r}")
            if endpoint in {"tags", "series", "series-pins"}:
                require(data["run"] == run and data["version"] == version and run and version,
                        "payload/manifest run or version mismatch")
            key = (run, version)
            if endpoint == "runs":
                require(isinstance(data["runs"], list), "runs must be a list")
                for tag, description in data.get("descriptions", {}).items():
                    item = {"text": description, "source": source(event, line, "/descriptions/" + pointer(tag))}
                    descriptions[tag].append(item)
                if "stream_start" in data:
                    event_row(event, line, "/stream_start", "", "", "stream_start",
                              time=data["stream_start"])
            elif endpoint == "tags":
                require(isinstance(data["tags"], list) and all(isinstance(t, str) for t in data["tags"]),
                        "tags must be strings")
                catalogs[key].append({"tags": data["tags"], "source": source(event, line, "/tags")})
            elif endpoint in {"series", "series-pins"}:
                steps, walls, series = data["steps"], data["walls"], data["series"]
                require(isinstance(steps, list) and all(integer(s) for s in steps), "invalid steps")
                require(isinstance(walls, list) and len(walls) == len(steps), "steps/walls length mismatch")
                require(all(w is None or number(w) for w in walls), "invalid walls")
                require(isinstance(series, dict), "series must map tags to value arrays")
                query = parse_qs(urlparse(event["url"]).query)
                wanted = set(filter(None, query.get("tags", [""])[0].split(",")))
                requested[key].update(wanted)
                returned[key].update(series)
                if wanted != set(series):
                    batch_discrepancies.append({"source": source(event, line),
                                               "missing": sorted(wanted - series.keys()),
                                               "extra": sorted(series.keys() - wanted)})
                if "run_start" in data:
                    event_row(event, line, "/run_start", run, version, "series_run_start", time=data["run_start"])
                for i, (step, wall) in enumerate(zip(steps, walls)):
                    grids[key][step].add(wall)
                    event_row(event, line, f"/walls/{i}", run, version, "series_step", step, wall,
                              "historical", {"meaning": "series wall timestamp; not inferred start/end"})
                for tag, values in series.items():
                    require(isinstance(values, list), f"{tag}: series is not a list")
                    require(len(values) in {0, len(steps)}, f"{tag}: values/steps length mismatch")
                    require(all(v is None or number(v) for v in values), f"{tag}: invalid numeric value")
                    metric = metrics.setdefault((*key, tag), {"points": defaultdict(dict), "sources": [],
                                                             "raw_slots": 0, "empty_responses": 0})
                    metric["sources"].append(source(event, line, "/series/" + pointer(tag)))
                    metric["raw_slots"] += len(values)
                    metric["empty_responses"] += not values
                    for i, (step, wall, value) in enumerate(zip(steps, walls, values)):
                        coordinate = (step, wall)
                        # A value variant keeps every locator; exact repeats do not inflate counts.
                        variant = metric["points"][coordinate].setdefault(canonical(value), {"value": value, "sources": []})
                        variant["sources"].append(source(event, line, f"/series/{pointer(tag)}/{i}"))
            elif endpoint == "status":
                require(data["run"]["key"] == run, "status run mismatch")
                version = data["version"]
                require(isinstance(version, str) and version, "missing status version")
                key = (run, version)
                require(integer(data["step"]["last"]), "invalid last completed step")
                statuses[key].append({"run": data["run"], "step": data["step"], "totals": data["totals"],
                                      "event_counts": dict(Counter(x["kind"] for x in data["events"])),
                                      "source": source(event, line)})
                for name in ("start", "end"):
                    if data["run"].get(name) is not None:
                        event_row(event, line, "/run/" + name, run, version, "run_" + name, time=data["run"][name])
                for i, item in enumerate(data["events"]):
                    require(isinstance(item, dict) and isinstance(item["kind"], str), "invalid status event")
                    if item["kind"] == "step":
                        observations.append((key, item["step"], item.get("t"), item.get("redo"), source(event, line, f"/events/{i}")))
                    event_row(event, line, f"/events/{i}", run, version, "status_" + item["kind"],
                              item.get("step"), item.get("t"),
                              "completed" if item["kind"] == "step" else "", item)
            elif endpoint == "live":
                require(run and version, "live response lacks manifest run/version")
                require(isinstance(data["entries"], list) and isinstance(data["latest"], dict), "invalid live schema")
                live[key].append({"log_time": data["log_time"], "latest": data["latest"],
                                  "entry_count": len(data["entries"]), "source": source(event, line)})
                for path, item in [(f"/entries/{i}", v) for i, v in enumerate(data["entries"])]+[("/latest", data["latest"])]:
                    require(integer(item["step"]) and number(item["t"]), "invalid live coordinate")
                    event_row(event, line, path, run, version,
                              "live_latest" if path == "/latest" else "live_sample",
                              item["step"], item["t"], "sampler_only", item)
            elif endpoint == "notices":
                require(isinstance(data["notices"], list), "notices must be a list")
                for i, item in enumerate(data["notices"]):
                    require(isinstance(item["text"], str), "notice text must be a string")
                    # Keep null scope even when prose names a run; do not infer an exact restart match.
                    event_row(event, line, f"/notices/{i}", item.get("run"), "", "notice",
                              time=item.get("t"), state="publisher_claim", details=item)
            elif endpoint == "benchmarks":
                require(isinstance(data["benchmarks"], list), "benchmarks must be a list")
                for i, benchmark in enumerate(data["benchmarks"]):
                    for result_run, results in benchmark["results"].items():
                        for step, value in results.items():
                            require(str(int(step)) == step and number(value), "invalid benchmark result")
                            event_row(event, line, f"/benchmarks/{i}/results/{pointer(result_run)}/{step}",
                                      result_run, "", "benchmark", int(step), state="offline_evaluation",
                                      details={"key": benchmark["key"], "title": benchmark["title"],
                                               "note": benchmark.get("note", ""), "value": value})
        except (ValueError, KeyError, TypeError, OverflowError, AttributeError) as exc:
            raise ArchiveError(f"manifest line {line}, endpoint {endpoint}: {exc}") from exc

    groups, rows = [], []
    all_keys = set(catalogs) | set(returned) | set(statuses) | set(live)
    for key in sorted(all_keys):
        run, version = key
        catalog = set(t for c in catalogs[key] for t in c["tags"])
        union = catalog | returned[key]
        observed_grid = set(grids[key])
        group_rows = []
        for tag in sorted(union):
            metric = metrics.get((*key, tag), {"points": {}, "sources": [], "raw_slots": 0, "empty_responses": 0})
            points = metric["points"]
            steps = sorted({s for s, _ in points})
            present_steps = sorted({s for (s, _), variants in points.items()
                                    if any(v["value"] is not None for v in variants.values())})
            unique_values = [v["value"] for variants in points.values() for v in variants.values()]
            conflicts = [{"step": s, "wall": w, "variants": list(variants.values())}
                         for (s, w), variants in sorted(points.items(), key=lambda x: (x[0][0], str(x[0][1])))
                         if len(variants) > 1]
            wall_variants = defaultdict(set)
            for s, w in points:
                wall_variants[s].add(w)
            numeric_values = [v for v in unique_values if v is not None]
            namespace = tag.split("/")[0]
            unit = "seconds" if namespace == "timing_s" else ""
            row = dict(run=run, version=version, tag=tag, namespace=namespace, family=namespace,
                       classification_basis="literal first path component; no mechanistic classification",
                       structural_pattern=re.sub(r"dataset-[^/]+", "{dataset}", tag),
                       unit=unit, unit_basis="timing_s namespace and dashboard wall-clock descriptions" if unit else "unknown",
                       catalog_present=tag in catalog, series_returned=tag in returned[key],
                       point_count=len(unique_values), unique_coordinate_count=len(points),
                       raw_slot_count=metric["raw_slots"], exact_duplicate_count=metric["raw_slots"]-len(unique_values),
                       empty_response_count=metric["empty_responses"],
                       null_count=sum(v is None for v in unique_values), nonnull_count=len(numeric_values),
                       conflict_count=len(conflicts), multiple_wall_steps=sorted(s for s,w in wall_variants.items() if len(w)>1),
                       first_step=min(steps) if steps else None, last_step=max(steps) if steps else None,
                       observed_steps=steps, nonnull_steps=present_steps,
                       missing_steps_relative_to_observed_grid=sorted(observed_grid-set(steps)),
                       null_only_steps=sorted(set(steps)-set(present_steps)),
                       min_value=min(numeric_values) if numeric_values else None,
                       max_value=max(numeric_values) if numeric_values else None,
                       descriptions=descriptions.get(tag, []), conflicts=conflicts, sources=metric["sources"])
            rows.append(row)
            group_rows.append(row)
        status_list = sorted(statuses[key], key=lambda s: s["source"]["captured_at"])
        live_list = sorted(live[key], key=lambda s: s["source"]["captured_at"])
        catalog_sets = {canonical(sorted(set(c["tags"]))) for c in catalogs[key]}
        groups.append(dict(run=run, version=version, catalog_count=len(catalog), returned_count=len(returned[key]),
                           requested_count=len(requested[key]), nonempty_count=sum(r["point_count"]>0 for r in group_rows),
                           with_nonnull_count=sum(r["nonnull_count"]>0 for r in group_rows),
                           missing_tags=sorted(catalog-returned[key]), extra_tags=sorted(returned[key]-catalog),
                           empty_tags=[r["tag"] for r in group_rows if r["series_returned"] and not r["point_count"]],
                           all_null_tags=[r["tag"] for r in group_rows if r["point_count"] and not r["nonnull_count"]],
                           null_slots=sum(r["null_count"] for r in group_rows),
                           metrics_with_nulls=sum(r["null_count"]>0 for r in group_rows),
                           null_slots_by_namespace={n: sum(r["null_count"] for r in group_rows if r["namespace"] == n)
                                                    for n in sorted({r["namespace"] for r in group_rows})},
                           unique_point_variants=sum(r["point_count"] for r in group_rows),
                           exact_duplicate_slots=sum(r["exact_duplicate_count"] for r in group_rows),
                           conflicting_coordinates=sum(r["conflict_count"] for r in group_rows),
                           namespaces=dict(sorted(Counter(r["namespace"] for r in group_rows).items())),
                           observed_steps=sorted(observed_grid),
                           walls_by_step={str(s): sorted(ws, key=str) for s,ws in sorted(grids[key].items())},
                           multiple_wall_steps=sorted(s for s,ws in grids[key].items() if len(ws)>1),
                           status_step_clock_checks=[{"step": s, "status_time": t, "redo": redo,
                               "series_times": sorted(grids[key].get(s, set()), key=str),
                               "result": ("no_series_coordinate" if s not in grids[key] else
                                          "exact_match" if t in grids[key][s] else "not_in_series"), "source": ref}
                               for observed_key,s,t,redo,ref in observations if observed_key == key],
                           catalog_snapshots=catalogs[key], catalog_conflict=len(catalog_sets)>1,
                           catalog_duplicate_entries=sum(len(c["tags"])-len(set(c["tags"])) for c in catalogs[key]),
                           status_snapshots=status_list, live_snapshots=live_list))
    tag_sets = {f"{g['run']}@{g['version']}": {r["tag"] for r in rows if (r["run"],r["version"]) == (g["run"],g["version"])} for g in groups}
    shared = set.intersection(*tag_sets.values()) if tag_sets else set()
    comparisons = {"shared_tags": sorted(shared), "exclusive_to_group": {
        k: sorted(v-set().union(*(other for name,other in tag_sets.items() if name != k))) for k,v in tag_sets.items()}}
    timeline_rows = sorted(timeline.values(), key=lambda r: (r["source_time_raw"] is None,
                          r["source_time_raw"] or 0, r["run"], r["version"], r["step"] or -1, r["event_kind"], canonical(r["details"])))
    capture_times = [e["captured_at"] for _,e,_ in records]
    inventory = dict(schema_version=1, manifest_sha256=digest(frozen),
                     analyzer_sha256=digest(Path(__file__).read_bytes()),
                     reproduction="python3 analysis/inventory.py --archive <archive-root> --out analysis",
                     archive=dict(manifest_entries=sum(endpoints.values()), successful_entries=len(records),
                                  failed_entries=len(failures), unique_objects=len(objects),
                                  decompressed_unique_bytes=sum(o["bytes"] for o in objects.values()),
                                  compressed_unique_bytes=sum(o["compressed_bytes"] for o in objects.values()),
                                  capture_first=min(capture_times), capture_last=max(capture_times),
                                  endpoint_counts=dict(sorted(endpoints.items())), integrity="all referenced successful objects verified",
                                  objects=objects, failures=failures),
                     endpoint_schemas={e:{p:sorted(ts) for p,ts in sorted(paths.items())} for e,paths in sorted(schemas.items())},
                     batch_discrepancies=batch_discrepancies, groups=groups, comparisons=comparisons,
                     metrics=rows, timeline_event_counts=dict(sorted(Counter(r["event_kind"] for r in timeline_rows).items())),
                     timestamp_interpretation="Numeric source times interpreted as Unix seconds, consistent with capture dates and cross-endpoint values; timestamp field semantics are preserved, not assumed to be step start/end.",
                     limitations=["Completeness is relative to the captured catalog, not all internal training telemetry.",
                                  "Historical arrays retain a published view; status may preserve earlier attempts, but complete metrics for overwritten attempts cannot be reconstructed here.",
                                  "Null is retained as unknown/missing, never converted to zero.",
                                  "Status event lists are bounded snapshots, not a complete restart history.",
                                  "Notices are publisher claims; null run scopes are not silently assigned from prose.",
                                  "Benchmark rows have no source timestamp or version; neither is borrowed from training series.",
                                  "Live sampler entries are not completed training steps.",
                                  "Units remain unknown except explicitly supported timing fields."])
    require(manifest.read_bytes() == frozen, "manifest changed during analysis")
    return inventory, timeline_rows


def markdown(inv, timeline):
    a = inv["archive"]
    lines = ["# 00 — MiMo archive inventory", "", "Generated offline from the captured archive; no dashboard requests.", "",
             f"- Manifest SHA-256: `{inv['manifest_sha256']}`",
             f"- Analyzer SHA-256: `{inv['analyzer_sha256']}`",
             f"- Capture window (UTC): {a['capture_first']} to {a['capture_last']}.",
             f"- {a['manifest_entries']} manifest entries: {a['successful_entries']} successful, {a['failed_entries']} failed requests.",
             f"- {a['unique_objects']} unique objects; all referenced successful gzip bodies pass SHA-256 and byte-count checks.",
             f"- Unique bytes: {a['compressed_unique_bytes']:,} compressed / {a['decompressed_unique_bytes']:,} decompressed.", "",
             "## Coverage", "", "| Run | Version | Catalog | Returned | With numeric values | Unique slots | Null slots | Conflicts |",
             "|---|---|---:|---:|---:|---:|---:|---:|"]
    for g in inv["groups"]:
        lines.append(f"| {g['run']} | `{g['version']}` | {g['catalog_count']} | {g['returned_count']} | {g['with_nonnull_count']} | {g['unique_point_variants']:,} | {g['null_slots']:,} | {g['conflicting_coordinates']} |")
    lines += ["", "Slots include nulls; repeated identical observations are counted once. Conflicting values are retained as variants.",
              "Catalog coverage is checked against returned payload keys, independently of the collector's request counter.", ""]
    for g in inv["groups"]:
        lines.append(f"- {g['run']}: missing tags {len(g['missing_tags'])}; extra tags {len(g['extra_tags'])}; empty arrays {len(g['empty_tags'])}; all-null arrays {len(g['all_null_tags'])}; duplicate slots {g['exact_duplicate_slots']}; catalog conflict {g['catalog_conflict']}. Observed historical steps: {g['observed_steps']}.")
        lines.append(f"  Nulls occur in {g['metrics_with_nulls']} metrics. Null slots by namespace: " + ", ".join(f"{n}={c}" for n,c in g['null_slots_by_namespace'].items() if c) + ".")
    lines += [f"- Request/response tag discrepancies: {len(inv['batch_discrepancies'])}.",
              f"- Shared exact tag names across groups: {len(inv['comparisons']['shared_tags'])}."]
    for k,v in inv["comparisons"]["exclusive_to_group"].items():
        lines.append(f"- Tags exclusive to {k}: {len(v)} (listed in inventory.json).")
    lines += ["", "## Metric taxonomy", "", "Families are literal top-level namespaces. Dataset IDs are additionally normalized in `structural_pattern`; no mechanism is inferred from a label.", "",
              "| Namespace | " + " | ".join(g["run"] for g in inv["groups"]) + " |",
              "|---|" + "---:|" * len(inv["groups"])]
    namespaces = sorted(set().union(*(g["namespaces"] for g in inv["groups"])))
    for n in namespaces:
        lines.append("| " + n + " | " + " | ".join(str(g["namespaces"].get(n,0)) for g in inv["groups"]) + " |")
    lines += ["", "## Timeline", "", inv["timestamp_interpretation"], "",
              "Timeline rows retain object hashes, manifest lines, JSON pointers, and capture times. Identical events combine source references. Untimed benchmarks sort after timed events; CSV row adjacency is not a causal assertion.", "",
              "| Run | Start (UTC) | End (UTC) | Last completed step | Latest sampler step | Reported restarts | Restarts in latest status event list |",
              "|---|---|---|---:|---:|---:|---:|"]
    for g in inv["groups"]:
        s = g["status_snapshots"][-1] if g["status_snapshots"] else {}
        l = g["live_snapshots"][-1] if g["live_snapshots"] else {}
        r = s.get("run", {})
        lines.append(f"| {g['run']} | {utc(r.get('start'))} | {utc(r.get('end'))} | {s.get('step',{}).get('last','')} | {l.get('latest',{}).get('step','')} | {s.get('totals',{}).get('restarts','')} | {s.get('event_counts',{}).get('restart','')} |")
    lines += ["", "The latest snapshot is selected by capture time for this table only; all snapshots remain in inventory.json.",
              "Differences between restart counters and event-list counts prevent a claim of complete restart reconstruction.", "",
              "Step-coordinate comparisons (differences can reflect distinct attempts, not clock error):", ""]
    for g in inv["groups"]:
        checks = Counter(c['result'] for c in g['status_step_clock_checks'])
        lines.append(f"- {g['run']}: steps with conflicting series wall timestamps {g['multiple_wall_steps']}; status-step timestamp checks across captures: {dict(checks)}.")
    absent = [(g, c) for g in inv['groups'] for c in g['status_step_clock_checks'] if c['result'] == 'not_in_series']
    if absent:
        lines += ["", "Status step occurrences absent from the retained series (deduplicated across captures):", "",
                  "| Run | Step | Earlier/status time (UTC) | Retained series time(s) (UTC) | Matching retained status redo flag(s) |",
                  "|---|---:|---|---|---|"]
        seen = set()
        for g,c in absent:
            key = g['run'], g['version'], c['step'], c['status_time']
            if key in seen:
                continue
            seen.add(key)
            redos = sorted({str(x['redo']) for x in g['status_step_clock_checks']
                            if x['step'] == c['step'] and x['result'] == 'exact_match'})
            lines.append(f"| {g['run']} | {c['step']} | {utc(c['status_time'])} | " +
                         ", ".join(utc(t) for t in c['series_times']) + " | " + ", ".join(redos) + " |")
        lines += ["", "These source distinctions are retained in timeline.csv; matching redo flags are publisher-supplied metadata."]
    lines += ["", "### Publisher notices", ""]
    for row in timeline:
        if row["event_kind"] == "notice":
            ref = row["sources"][0]
            lines.append(f"- {row['source_time_utc']}: {row['details']['text']} (manifest line {ref['manifest_line']}, `{ref['json_pointer']}`; structured run scope: {row['run'] or 'null'}).")
    lines += ["", "## Interpretation boundary and next questions", "",
              "This pass describes the public archive. Direct dataset/harness labels must stay separate from operational measurements in any later workload-classification evaluation.",
              "The observed timing_s family, perf token count, and environment/sampler fields are candidate operational observables. Their availability alone does not identify an interconnect or TP/PP/DP strategy.",
              "The parallelism-change notice is a publisher statement, not an independently identified configuration or precisely matched intervention.", "",
              "Before hypotheses: inspect null patterns and cross-endpoint clock agreement; establish which quantities are measured, derived, or merely named; read the original SPAR proposal and map its required observables to the inventory.", "", "## Limitations", ""]
    lines += ["- " + s for s in inv["limitations"]]
    return "\n".join(lines) + "\n"


def write_outputs(inv, timeline, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    # One metric per line keeps the large inventory diff reviewable.
    with (out / "inventory.json").open("w") as f:
        f.write("{\n")
        for i, (key, value) in enumerate(sorted(inv.items())):
            if i:
                f.write(",\n")
            f.write("  " + json.dumps(key) + ": ")
            if key == "metrics":
                f.write("[\n" + ",\n".join("    " + canonical(row) for row in value) + "\n  ]")
            else:
                f.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False))
        f.write("\n}\n")
    (out / "00-inventory.md").write_text(markdown(inv, timeline))
    fields = [k for k in inv["metrics"][0] if k not in {"conflicts", "descriptions"}] if inv["metrics"] else ["run", "version", "tag"]
    with (out / "metric-families.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in inv["metrics"]:
            writer.writerow({k: canonical(v) if isinstance(v,(list,dict)) else v for k,v in row.items()})
    with (out / "timeline.csv").open("w", newline="") as f:
        fields = ["run", "version", "event_kind", "step", "source_time_raw", "source_time_utc", "time_basis",
                  "completion_state", "details_json", "captured_at", "manifest_line", "object_sha256", "json_pointer", "sources_json"]
        writer = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in timeline:
            ref = min(row["sources"], key=lambda s:s["captured_at"])
            writer.writerow({**{k:v for k,v in row.items() if k not in {"sources", "details"}},
                             **ref, "details_json": canonical(row["details"]), "sources_json": canonical(row["sources"])})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True, help="directory containing manifest.ndjson and objects/")
    parser.add_argument("--out", type=Path, default=Path("analysis"))
    args = parser.parse_args()
    try:
        require(not args.out.resolve().is_relative_to(args.archive.resolve()), "output must be outside the input archive")
        inv, timeline = analyze(args.archive)
        write_outputs(inv, timeline, args.out)
    except (ArchiveError, OSError) as exc:
        parser.exit(1, f"inventory: {exc}\n")
    print(f"Verified {inv['archive']['unique_objects']} objects; wrote {len(inv['metrics'])} metric rows and {len(timeline)} timeline rows to {args.out}")


if __name__ == "__main__":
    main()
