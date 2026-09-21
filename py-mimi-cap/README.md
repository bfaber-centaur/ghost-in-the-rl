# mimo-capture

Tiny reconnaissance recorder for Xiaomi's public MiMo-V2.6 RL dashboard.

It deliberately does **not** assume an API schema. It keeps the dashboard open,
records response metadata, saves JSON/text bodies content-addressed by SHA-256,
records WebSocket frames, and snapshots the rendered page text once a minute.

## Run

Using `uv` and an installed Google Chrome:

```bash
uv run --with playwright python mimo_capture.py --headed
```

If you do not have Chrome, install Playwright's Chromium once:

```bash
uv run --with playwright playwright install chromium
uv run --with playwright python mimo_capture.py --channel ''
```

Quick 90-second discovery run:

```bash
uv run --with playwright python mimo_capture.py --duration 90 --headed
```

Output:

```text
data/mimo/
  events.ndjson     # endpoint discovery + websocket events + snapshot metadata
  bodies/           # deduplicated response bodies, keyed by sha256
  pages/            # rendered dashboard text snapshots
```

Useful first inspection:

```bash
jq -r 'select(.kind=="response") | [.status,.content_type,.url] | @tsv' \
  data/mimo/events.ndjson | sort -u
```

Once the actual telemetry endpoints are identified, the next step is to replace
this browser recorder with a much smaller direct HTTP Go poller and normalize the
specific series we care about into stable NDJSON/Parquet.
