#!/usr/bin/env python3
"""Capture Xiaomi MiMo RL dashboard telemetry without assuming its API schema.

The recorder keeps the dashboard open in Chromium, logs response metadata, saves
JSON/text response bodies content-addressed by SHA-256, records websocket frames,
and periodically snapshots the rendered page text as a fallback.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import signal
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright, Response, WebSocket

DEFAULT_URL = "https://mimo.xiaomi.com/rl/"
INTERESTING_CONTENT_TYPES = (
    "application/json",
    "text/json",
    "text/plain",
    "text/event-stream",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def safe_json(value: Any) -> Any:
    if isinstance(value, bytes):
        return {"encoding": "hex", "data": value.hex()}
    return value


class Recorder:
    def __init__(self, out: Path, host_filter: str, max_body_bytes: int) -> None:
        self.out = out
        self.host_filter = host_filter
        self.max_body_bytes = max_body_bytes
        self.bodies = out / "bodies"
        self.pages = out / "pages"
        self.events_path = out / "events.ndjson"
        self.bodies.mkdir(parents=True, exist_ok=True)
        self.pages.mkdir(parents=True, exist_ok=True)
        self._write_lock = asyncio.Lock()
        self._tasks: set[asyncio.Task[Any]] = set()

    def track(self, coro: Any) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def emit(self, record: dict[str, Any]) -> None:
        record = {"captured_at": utc_now(), **record}
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        async with self._write_lock:
            with self.events_path.open("a", encoding="utf-8") as f:
                f.write(line)

    async def save_body(self, body: bytes, suffix: str = ".bin") -> tuple[str, str]:
        digest = hashlib.sha256(body).hexdigest()
        path = self.bodies / f"{digest}{suffix}"
        if not path.exists():
            path.write_bytes(body)
        return digest, str(path.relative_to(self.out))

    async def on_response(self, response: Response) -> None:
        url = response.url
        if self.host_filter not in url:
            return

        headers = await response.all_headers()
        content_type = headers.get("content-type", "").lower()
        record: dict[str, Any] = {
            "kind": "response",
            "url": url,
            "status": response.status,
            "content_type": content_type,
        }

        # Always log metadata so this doubles as endpoint discovery.
        should_read = any(ct in content_type for ct in INTERESTING_CONTENT_TYPES)
        if not should_read:
            await self.emit(record)
            return

        try:
            body = await response.body()
        except Exception as exc:
            record["body_error"] = repr(exc)
            await self.emit(record)
            return

        record["bytes"] = len(body)
        if len(body) > self.max_body_bytes:
            record["body_skipped"] = f"larger than {self.max_body_bytes} bytes"
            await self.emit(record)
            return

        suffix = ".json" if "json" in content_type else ".txt"
        digest, rel = await self.save_body(body, suffix)
        record["sha256"] = digest
        record["body_path"] = rel
        await self.emit(record)

    def on_websocket(self, ws: WebSocket) -> None:
        self.track(self.emit({"kind": "websocket_open", "url": ws.url}))

        def received(payload: Any) -> None:
            self.track(self.emit({
                "kind": "websocket_received",
                "url": ws.url,
                "payload": safe_json(payload),
            }))

        def sent(payload: Any) -> None:
            self.track(self.emit({
                "kind": "websocket_sent",
                "url": ws.url,
                "payload": safe_json(payload),
            }))

        def closed() -> None:
            self.track(self.emit({"kind": "websocket_closed", "url": ws.url}))

        ws.on("framereceived", received)
        ws.on("framesent", sent)
        ws.on("close", closed)

    async def snapshot_page(self, page: Any) -> None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        try:
            text = await page.locator("body").inner_text()
            path = self.pages / f"{stamp}.txt"
            path.write_text(text, encoding="utf-8")
            await self.emit({
                "kind": "page_snapshot",
                "url": page.url,
                "body_path": str(path.relative_to(self.out)),
                "bytes": len(text.encode("utf-8")),
            })
        except Exception as exc:
            await self.emit({"kind": "page_snapshot_error", "error": repr(exc)})

    async def drain(self) -> None:
        if self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)


async def run(args: argparse.Namespace) -> None:
    out = Path(args.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    recorder = Recorder(out, args.host_filter, args.max_body_mb * 1024 * 1024)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass

    async with async_playwright() as p:
        launch_kwargs: dict[str, Any] = {"headless": not args.headed}
        if args.executable:
            launch_kwargs["executable_path"] = args.executable
        elif args.channel:
            launch_kwargs["channel"] = args.channel

        browser = await p.chromium.launch(**launch_kwargs)
        context = await browser.new_context()
        page = await context.new_page()

        page.on("response", lambda response: recorder.track(recorder.on_response(response)))
        page.on("websocket", recorder.on_websocket)

        await recorder.emit({"kind": "capture_start", "url": args.url})
        await page.goto(args.url, wait_until="domcontentloaded", timeout=args.nav_timeout_ms)

        # Give the overview a chance to lazy-load, then trigger the metrics view too.
        await page.wait_for_timeout(args.warmup_seconds * 1000)
        await recorder.snapshot_page(page)
        try:
            metrics = page.get_by_text("metrics", exact=True)
            if await metrics.count():
                await metrics.first.click(timeout=3000)
                await page.wait_for_timeout(3000)
        except Exception as exc:
            await recorder.emit({"kind": "metrics_click_error", "error": repr(exc)})

        async def snapshot_loop() -> None:
            while not stop.is_set():
                await recorder.snapshot_page(page)
                try:
                    await asyncio.wait_for(stop.wait(), timeout=args.snapshot_every)
                except asyncio.TimeoutError:
                    pass

        snapshot_task = asyncio.create_task(snapshot_loop())

        if args.duration > 0:
            try:
                await asyncio.wait_for(stop.wait(), timeout=args.duration)
            except asyncio.TimeoutError:
                stop.set()
        else:
            await stop.wait()

        snapshot_task.cancel()
        await asyncio.gather(snapshot_task, return_exceptions=True)
        await recorder.snapshot_page(page)
        await recorder.emit({"kind": "capture_stop", "url": page.url})
        await recorder.drain()
        await context.close()
        await browser.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture MiMo RL dashboard telemetry")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--out", default="data/mimo")
    parser.add_argument("--host-filter", default="mimo.xiaomi.com")
    parser.add_argument("--snapshot-every", type=int, default=60, help="rendered-page snapshot interval, seconds")
    parser.add_argument("--duration", type=int, default=0, help="stop after N seconds; 0 means until Ctrl-C")
    parser.add_argument("--warmup-seconds", type=int, default=5)
    parser.add_argument("--max-body-mb", type=int, default=32)
    parser.add_argument("--nav-timeout-ms", type=int, default=30_000)
    parser.add_argument("--headed", action="store_true", help="show the browser window")
    parser.add_argument("--channel", default="chrome", help="Playwright Chromium channel; default: chrome")
    parser.add_argument("--executable", default="", help="explicit Chromium/Chrome executable path")
    return parser.parse_args()


if __name__ == "__main__":
    asyncio.run(run(parse_args()))
