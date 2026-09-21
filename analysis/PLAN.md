# 00 — Archive inventory and timeline

Status: implemented and run against the uploaded archive. See `README.md` for
the actual interface/schema conventions and `00-inventory.md` for results.
Collector reviewed at commit `807f546ccc6e072ff926a7ba4d496deb1aab84d4`.

## Scope

Characterize the public dashboard archive before proposing mechanisms. Treat
Pro 2,029 / Flash 2,062 tags and completed step 30 / partial live step 31 as
reported expectations to check, not measurements already reproduced here.
The archive was subsequently supplied and inspected before parser implementation.

## Minimal sequence

1. Freeze the input: SHA-256 the manifest bytes, record analyzer revision and
   arguments, and verify every referenced successful object against its
   decompressed-body SHA-256 and byte count. Count failed requests separately.
   Detect a manifest change during analysis and abort rather than mix snapshots.
2. Inspect actual JSON schemas for every endpoint and run/version. Enumerate
   catalog tags and returned series independently. Report requested, returned,
   nonempty, missing, extra, and empty tags. Preserve conflicting catalog snapshots.
3. Inventory points: observed step sets, gaps, null/nonfinite values, exact
   duplicate observations, conflicting values at the same coordinates, and
   schema exceptions. Keep run/version boundaries. Do not silently prefer the
   latest response when historical series disagree.
4. Build a lexical taxonomy from observed tag names. Retain exact tags and
   namespace prefixes; add semantic labels only with an explicit mapping rule
   and evidence. Leave unknown units, aggregation, and meanings unknown.
5. Reconstruct a source-backed timeline using explicit source timestamps and
   step fields. Keep capture time, source event time, and training step separate.
   Preserve notices as publisher claims. Keep live sampler state separate from
   completed series. Do not turn a step into a timestamp without evidence.
6. Generate all four artifacts in one offline pass. Review coverage and clock
   semantics before opening a hypothesis-testing phase.

## Tooling

Use a Python standard-library CLI (`argparse`, `gzip`, `hashlib`, `json`, `csv`,
`datetime`, `pathlib`, `collections`). No API requests, dataframe dependency,
notebook, or database is needed for this pass. Read the archive without changing
it; write deterministic outputs to a separate output directory. Reject object
paths outside the archive root. Validate explicit endpoint schemas rather than
silently accepting heuristic field guesses. Unknown schemas must produce an
actionable diagnostic and prevent a clean/completeness claim.

Implemented interface:

```bash
python3 analysis/inventory.py \
  --archive mimo-capture-go/data/mimo \
  --out analysis
```

Tests should target integrity failures, HTTP success with absent/empty series,
overlapping batches and conflicting points, version separation, mixed clock
fields, and partial live steps. Fixtures should derive from inspected payloads;
synthetic fixtures must never be represented as captured results.

## Output contract

### `00-inventory.md`

Readable summary of verified archive integrity, endpoint/schema coverage,
run/version and tag coverage, observed metric namespaces, step and timestamp
coverage, discrepancies, and unresolved interpretation questions. Include a
provenance section and an explicit distinction between verified findings and
publisher/user-reported context. Generate from the same inventory structure as
the machine-readable outputs.

### `inventory.json`

Versioned schema containing input manifest hash, analyzer provenance, manifest
entry/unique object/byte counts, capture-time span, endpoint schemas, integrity
findings, run/version catalog and actual-series coverage, per-metric point
summaries, duplicates/conflicts, and source references. Retain manifest line,
object hash, and JSON pointer for traceability. Repeated captures must not
inflate unique observation counts.

### `metric-families.csv`

One row per `(run, version, tag)`, using the union of catalog and returned tags.
Columns: run, version, tag, namespace, family, classification_basis,
unit, unit_basis, catalog_present, series_returned, point_count,
unique_coordinate_count, null_count, conflict_count, first_step, last_step,
observed_steps_json, missing_steps_json, source_refs_json.
Only enumerate missing steps within a documented expected grid; otherwise
leave that field unknown. Report shared and run-specific tags in the inventory.

### `timeline.csv`

One row per source-backed event or step observation, with columns:
run, version, event_kind, step, source_time_raw, source_time_utc,
time_basis, captured_at, completion_state, description,
manifest_line, object_sha256, json_pointer.
Normalize timestamps only when units and timezone semantics are established.
Rows lacking source time remain present, with a blank normalized time.
Do not imply that series logging timestamps are step start/end times.

## Research boundary

This is curated application telemetry. Whether the archive contains coarse
operational signals, direct workload labels, network counters, timing measures,
or other relevant observables must be established by inventory. A dashboard
label is not an independently inferred workload classification. No inference
about TP/PP/DP, interconnect, or bytes-per-sync scaling is warranted from metric
names alone. Preserve semantic labels separately so a later comparison can ask
what remains inferable when those labels are withheld.

Before the SPAR comparison, read the original proposal and record its exact
observable requirements and assumptions alongside the fields actually present.
This initial pass does not evaluate or revise that proposal.
