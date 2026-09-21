# mimo-capture

Tiny stdlib-only Go collector for Xiaomi MiMo's public RL dashboard.

The browser reconnaissance pass showed that the page is backed by ordinary JSON endpoints (`/api/runs`, `/api/status`, `/api/live`, `/api/notices`, `/api/benchmarks`, `/api/tags`, `/api/series`). This version talks to those endpoints directly; Playwright is no longer needed.

## One-shot archival snapshot

Both visible MiMo v2.6 runs are currently marked ended, so this is the useful mode right now:

```bash
go run . -out data/mimo
```

By default it will:

1. save run metadata, notices, and benchmarks;
2. save each run's status and final live/dynamic-sampler state;
3. save the complete metric-tag catalog for each run/version;
4. backfill **all historical metric series** in batches of 50 tags.

The archive is content-addressed and gzip-compressed:

```text
data/mimo/
  manifest.ndjson
  objects/
    <sha256>.json.gz
```

`manifest.ndjson` records the capture time, exact endpoint URL, run/version, byte count, SHA-256, and object path for every response. Identical bodies reuse the same object.

Backfills are resumable. On startup the collector reads successful historical `/series` entries from `manifest.ndjson` and skips metric tags already captured, even if a previous run used a different batch shape. Transient HTTP failures are retried with exponential backoff; if a `/series` batch still fails, the batch is recursively split so one large or pathological request does not discard the rest of the archive.

The default retry count is four additional attempts. You can change it with:

```bash
go run . -retries 6 -out data/mimo
```

To skip the full ~2,000-tag historical backfill:

```bash
go run . -backfill=false
```

## Watch mode

If Xiaomi starts another run or resumes live activity:

```bash
go run . -watch -interval 30s -out data/mimo
```

Watch mode keeps polling public run/live/notices/benchmark state. When it sees a new run version, it saves the new tag catalog and backfills that version. When the completed-step number changes, it refreshes the dashboard's pinned historical metrics.

## Inspecting an archived object

```bash
gzip -dc data/mimo/objects/<sha256>.json.gz | jq .
```

Find the object for an endpoint with:

```bash
jq -r 'select(.endpoint=="status" and .run=="pro") | [.captured_at,.sha256,.object] | @tsv' data/mimo/manifest.ndjson
```

## Notes from the first capture

The API distinguishes the completed training series from the in-flight sampler. Both `pro` and `flash` are marked `mode: "ended"` at completed step 30, while `/api/live` still contains a partial step-31 sampler state. That makes the final `/live` response worth preserving even though step 31 never appears in the completed `/series` history.

The public notices also explain several discontinuities, including Pro restarts for VRAM/OOM/network issues and the removal of the cyber dataset from later Pro training.
