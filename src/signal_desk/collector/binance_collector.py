from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any

import requests
import websockets

from signal_desk.config.loader import validate_config
from signal_desk.collector.binance_mapping import map_depth_delta, map_snapshot, map_trade, utc_now_iso
from signal_desk.collector.order_book_state import L2BookState, OrderBookGap
from signal_desk.storage.jsonl import append_jsonl
from signal_desk.schemas.validate import validate_json


def fetch_depth_snapshot(rest_base_url: str, symbol: str, limit: int) -> dict:
    url = f"{rest_base_url.rstrip('/')}/api/v3/depth"
    resp = requests.get(url, params={"symbol": symbol, "limit": limit}, timeout=10)
    resp.raise_for_status()
    return resp.json()


def write_status(config: dict, status: str, reason: str | None = None, **extra: Any) -> None:
    base = Path(config["storage"]["base_path"])
    path = base / "status" / "collector_status.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": status,
        "reason": reason,
        "symbol": config["exchange"]["symbol"],
        "mode": config["project"]["mode"],
        "execution_enabled": config["project"]["execution_enabled"],
        "ts": utc_now_iso(),
        **extra,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def raw_file(config: dict, suffix: str) -> Path:
    symbol = config["exchange"]["symbol"].lower()
    day = utc_now_iso()[:10]
    return Path(config["storage"]["raw_path"]) / f"binance_{symbol}_{suffix}_{day}.jsonl"


def write_event(config: dict, event: dict) -> None:
    validate_json(event, "market_event.schema.json")
    suffix = "depth" if event["event_type"] in {"book_snapshot", "book_delta"} else "trade"
    append_jsonl(raw_file(config, suffix), event)


def run_once(config_path: str) -> int:
    config = validate_config(config_path)
    ex = config["exchange"]
    snapshot = fetch_depth_snapshot(ex["endpoints"]["rest_base_url"], ex["symbol"], int(ex["market_data"]["snapshot_limit"]))
    event = map_snapshot(snapshot, symbol=ex["symbol"], raw_stream="rest_depth_snapshot")
    write_event(config, event)
    write_status(config, "RUNNING", "snapshot_written", last_update_id=event["last_update_id"])
    print(json.dumps({"status": "ok", "raw_path": str(raw_file(config, "depth")), "last_update_id": event["last_update_id"]}))
    return 0


def stream_url(config: dict) -> str:
    ex = config["exchange"]
    streams = [ex["market_data"]["depth_stream"], ex["market_data"]["trade_stream"]]
    base = ex["endpoints"]["ws_base_url"].rstrip("/")
    return f"{base}/stream?streams={'/'.join(streams)}"


class StreamSyncError(RuntimeError):
    pass


# Smoke-test bounds, not a claim of continuous collector readiness.
STREAM_BUFFER_LIMIT = 256
STREAM_MESSAGE_MAX_BYTES = 256 * 1024
STREAM_WAIT_SECONDS = 10
SNAPSHOT_ATTEMPTS = 3


async def collect_connected_stream(ws: Any, config: dict, max_events: int | None) -> dict:
    """Buffer before REST; publish RUNNING only after a depth update bridges the snapshot."""
    from collections import deque

    ex = config["exchange"]
    symbol = ex["symbol"]
    queue: asyncio.Queue = asyncio.Queue(maxsize=STREAM_BUFFER_LIMIT)

    async def receive() -> None:
        try:
            async for raw in ws:
                message = json.loads(raw)
                # Map at receipt, so REST latency doesn't become received_ts.
                payload = message.get("data", message)
                kind = payload.get("e")
                if kind == "depthUpdate":
                    event = map_depth_delta(payload, symbol=symbol, raw_stream=message.get("stream"))
                elif kind == "trade":
                    event = map_trade(payload, symbol=symbol, raw_stream=message.get("stream"))
                else:
                    continue
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull as exc:
                    raise StreamSyncError("WebSocket buffer overflow; restart synchronization") from exc
            raise StreamSyncError("WebSocket closed before smoke test completed")
        except Exception as exc:
            # Wake a waiting consumer; when full it checks reader.result() first.
            try:
                queue.put_nowait(exc)
            except asyncio.QueueFull:
                pass
            raise

    reader = asyncio.create_task(receive())

    async def next_event() -> dict:
        if reader.done():
            reader.result()
        try:
            event = await asyncio.wait_for(queue.get(), STREAM_WAIT_SECONDS)
        except asyncio.TimeoutError as exc:
            raise StreamSyncError("Timed out waiting for market data") from exc
        if isinstance(event, Exception):
            raise event
        return event

    try:
        pending: deque = deque()
        write_status(config, "SYNCING", "buffering_before_snapshot")
        # Wait for the first depth event, retaining earlier trades in arrival order.
        while True:
            event = await next_event()
            pending.append(event)
            if event["event_type"] == "book_delta":
                first_depth_id = event["first_update_id"]
                break
            if len(pending) >= STREAM_BUFFER_LIMIT:
                raise StreamSyncError("No depth event within bootstrap buffer limit")

        for attempt in range(1, SNAPSHOT_ATTEMPTS + 1):
            # Blocking REST must not prevent the receiver from buffering WS events.
            snapshot = await asyncio.to_thread(
                fetch_depth_snapshot, ex["endpoints"]["rest_base_url"], symbol,
                int(ex["market_data"]["snapshot_limit"]),
            )
            if reader.done():
                reader.result()
            if int(snapshot["lastUpdateId"]) >= first_depth_id:
                break
            write_status(config, "SYNCING", "snapshot_behind_buffer", snapshot_attempt=attempt)
        else:
            raise StreamSyncError("Snapshot remained behind first buffered depth event")

        book = L2BookState()
        snapshot_event = map_snapshot(snapshot, symbol=symbol, raw_stream="rest_depth_snapshot")
        book.apply_snapshot(snapshot_event)
        write_event(config, snapshot_event)
        written = 1
        depth_events = trade_events = stale_depth_events = 0
        synchronized = False
        while True:
            if reader.done():
                reader.result()
            event = pending.popleft() if pending else await next_event()
            if event["event_type"] == "book_delta":
                previous_id = book.last_update_id
                if event["final_update_id"] <= previous_id:
                    stale_depth_events += 1
                    continue
                book.apply_delta(event)  # Gaps still fail closed.
                event["previous_final_update_id"] = previous_id
                depth_events += 1
                if not synchronized:
                    synchronized = True
                    write_status(config, "RUNNING", "depth_bridge_applied",
                                 last_update_id=book.last_update_id)
            else:
                trade_events += 1
            write_event(config, event)
            written += 1
            stats = dict(written_events=written, depth_events=depth_events,
                         trade_events=trade_events, stale_depth_events=stale_depth_events,
                         gap_count=0, last_update_id=book.last_update_id)
            if synchronized and written % 100 == 0:
                write_status(config, "RUNNING", "streaming", **stats)
            # Trades alone must never qualify a synchronized-book smoke test.
            if synchronized and max_events is not None and written >= max_events:
                write_status(config, "STOPPED", "max_events_reached", **stats)
                return stats
    finally:
        reader.cancel()
        await asyncio.gather(reader, return_exceptions=True)


async def run_stream_async(config_path: str, max_events: int | None = None) -> int:
    config = validate_config(config_path)
    try:
        if max_events is not None and max_events < 2:
            raise ValueError("--max-events must be at least 2 (snapshot and depth bridge)")
        write_status(config, "CONNECTING", "opening_websocket")
        async with websockets.connect(
            stream_url(config), ping_interval=20, ping_timeout=10, close_timeout=5,
            open_timeout=10, max_size=STREAM_MESSAGE_MAX_BYTES, max_queue=16,
        ) as ws:
            stats = await collect_connected_stream(ws, config, max_events)
        print(json.dumps({"status": "ok", **stats}), flush=True)
        return 0
    except (OrderBookGap, StreamSyncError) as exc:
        gap_count = int(isinstance(exc, OrderBookGap))
        write_status(config, "RESYNCING", str(exc), gap_count=gap_count)
        print(json.dumps({"status": "RESYNCING", "reason": str(exc),
                          "gap_count": gap_count}), flush=True)
        return 2
    except Exception as exc:
        write_status(config, "ERROR", str(exc))
        print(json.dumps({"status": "ERROR", "reason": str(exc)}), flush=True)
        return 1


def run_stream(config_path: str, max_events: int | None = None) -> int:
    return asyncio.run(run_stream_async(config_path, max_events=max_events))


def run_idle(config_path: str) -> int:
    config = validate_config(config_path)
    write_status(config, "IDLE", "collector ready; use --mode once or --mode stream for market data")
    print("collector_idle paper_only=true execution_enabled=false")
    while True:
        time.sleep(3600)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["idle", "once", "stream"], default="idle")
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--max-events", type=int, default=None, help="Stop stream mode after N written events; useful for VPS smoke tests")
    args = parser.parse_args()
    if args.mode == "once":
        return run_once(args.config)
    if args.mode == "stream":
        return run_stream(args.config, max_events=args.max_events)
    return run_idle(args.config)


if __name__ == "__main__":
    raise SystemExit(main())
