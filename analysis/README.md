# Offline inventory

Python 3.10+; standard library only. From the repository root:

```bash
python3 analysis/inventory.py --archive mimo-capture-go/data/mimo --out analysis
python3 -m unittest discover -s analysis -p 'test_*.py' -v
```

`--archive` is the directory containing `manifest.ndjson` and `objects/`.
No dashboard requests are made. Inputs are read-only, and output must be outside
that directory. All successful object references are checked against the
SHA-256 of their decompressed bodies and recorded byte lengths. A malformed
manifest, corrupt/missing object, unsupported endpoint, incompatible required
schema, or nonnumeric/nonfinite series value produces a nonzero exit before
output generation. A changing manifest also aborts. Existing reports are not
removed on failure: check the command's exit status before using old output.

Missing/empty returned series, catalog changes, nulls, conflicting observations,
and failed HTTP requests are findings, not automatic parser failures. Consult
these fields before claiming coverage; a successful analyzer exit alone does
not mean every requested tag returned data.

## Outputs

- `00-inventory.md`: generated overview, namespace counts, run chronology,
  publisher notices, and interpretation limits.
- `inventory.json`: schema version 1, manifest/analyzer hashes, object integrity,
  endpoint type paths, run/version coverage, catalog/status/live snapshots,
  per-metric summaries, and conflicts. Large metric records occupy one line each
  to make regenerated diffs manageable.
- `metric-families.csv`: one row per run/version/tag in the union of catalog and
  returned series. `family` is the literal namespace; `structural_pattern`
  replaces dataset identifiers with `{dataset}`. This is a lexical inventory,
  not a workload classifier.
- `timeline.csv`: explicit series wall coordinates, status events, run bounds,
  stream start, notices, live samples/latest state, and untimed benchmark results.

JSON objects/lists in CSV cells are JSON-encoded; blank scalar cells mean unknown
or not supplied. `point_count` counts distinct value variants at `(step, wall)`;
`unique_coordinate_count` counts coordinates. `raw_slot_count` includes repeated
responses. `exact_duplicate_count` removes repeated copies of the same value at
the same coordinate. Null is a distinct retained value, never zero. Conflicting
values at one coordinate retain all variants and their point-level locators.
Multiple wall timestamps at one step are reported separately.

`observed_steps` includes coordinates with null values; `nonnull_steps` does not.
`missing_steps_relative_to_observed_grid` compares against the union of steps
actually returned for that run/version, not an assumed global logging frequency.
No missing step implies zero activity. No empty series implies zero values.

Source references contain a 1-based manifest line, object SHA-256, RFC 6901 JSON
pointer, and capture timestamp. Per-metric references point to the value array,
whose indexes align with that object's `steps` and `walls` arrays. Identical
timeline rows combine all sources. Convenience locator columns point to the
first capture; `sources_json` retains the full set. Fields and semantic labels
are preserved separately from any inferred interpretation.

Numeric source timestamps are interpreted as Unix seconds, consistent with
calendar dates and cross-endpoint agreement. This is an explicit interpretation,
not a claim about clock accuracy or whether a series `wall` means step start or
completion. Raw values and source pointers remain available. Benchmarks have no
source event time/version, so these fields stay blank. Notices with null run
scope stay unscoped even when prose names a run. `live_latest` and `live_sample`
are distinct source roles and can describe the same time; neither implies a
completed step. Rows from multiple endpoints may describe the same underlying
event without being collapsed into a causal reconstruction.

The complete catalog, schemas, and repeated snapshots are retained in the JSON
for inspection; a union catalog does not conceal differing captured catalogs.
Status rows recover version from the payload because the collector's status
manifest entry omits it. Live rows use the manifest version. API-wide notices,
benchmarks, and stream metadata have no invented version assignment.

## Reproducibility and scope

Outputs are deterministic for the same archive and analyzer bytes. Neither
local paths nor analysis wall-clock time are embedded. The manifest hash binds
the exact capture ledger; object hashes bind the successful response bodies.
The analyzer hash binds the generating script. All output files should be
regenerated together after changes.

Tests construct explicitly synthetic archives in the observed endpoint shapes.
They cover integrity failures, absent/empty/null series, duplicate/conflicting
points, run/version identity, multiple wall times, catalog changes, unknown
schemas, live/completed separation, untimed benchmarks, and deterministic output.
No raw capture is committed as a fixture.

This initial pass does not evaluate the SPAR proposal or fit a workload model.
The next step is to read that proposal and map required measurements onto actual
available fields, retaining the distinction between direct labels and coarse
operational observations.
