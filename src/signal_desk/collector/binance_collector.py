from __future__ import annotations

import argparse
import asyncio
import json
import time
import sys
import os
from pathlib import Path
from typing import Any

import requests
import websockets

from signal_desk.collector.recovery import RecoveryPolicy
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
        **config.get("_collector_runtime", {}),
    }
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def raw_file(config: dict, suffix: str) -> Path:
    symbol = config["exchange"]["symbol"].lower()
    day = utc_now_iso()[:10]
    return Path(config["storage"]["raw_path"]) / f"binance_{symbol}_{suffix}_{day}.jsonl"


class CollectorStorageError(RuntimeError):
    pass


def write_event(config: dict, event: dict) -> None:
    validate_json(event, "market_event.schema.json")
    suffix = "depth" if event["event_type"] in {"book_snapshot", "book_delta"} else "trade"
    runtime = config.get("_collector_runtime")
    if runtime is not None:
        event = {**event, "data_quality": {**event.get("data_quality", {}),
                                         "collector_session_id": runtime["session_id"]}}
    size = len((json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))
    guard = config.get("_storage_guard")
    try:
        if guard is not None:
            guard.check(size)
        append_jsonl(raw_file(config, suffix), event)
    except OSError as exc:
        raise CollectorStorageError(str(exc)) from exc
    if guard is not None:
        guard.used += size
    if runtime is not None:
        runtime["total_written_events"] += 1
        runtime["total_depth_events"] += int(event["event_type"] == "book_delta")
        runtime["total_trade_events"] += int(event["event_type"] == "trade")
        runtime["raw_bytes"] = guard.used if guard is not None else None


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



class SnapshotRequestError(OSError):
    def __init__(self, reason, http_status=None):
        super().__init__(reason)
        self.http_status = http_status


async def fetch_snapshot_async(rest_base_url, symbol, limit, timeout=15):
    """Isolate blocking HTTP/DNS so cancellation actually terminates the request."""
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "signal_desk.collector.snapshot_request",
        rest_base_url.rstrip("/") + "/api/v3/depth", symbol, str(limit),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        output, error = await asyncio.wait_for(process.communicate(), timeout)
    except BaseException:
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        await process.communicate()
        raise
    if len(output) > 2 * 1024 * 1024 + 1024:
        raise ValueError("Snapshot helper output exceeded limit")
    result = json.loads(output)
    if process.returncode:
        if result.get("fatal"):
            raise ValueError(result["error"])
        raise SnapshotRequestError(result.get("error", "Snapshot helper failed"),
                                   result.get("http_status"))
    return result


async def collect_connected_stream(ws: Any, config: dict, max_events: int | None, *, on_progress=None) -> dict:
    """Buffer before REST; publish RUNNING only after a depth update bridges the snapshot."""
    from collections import deque

    ex = config["exchange"]
    symbol = ex["symbol"]
    policy = RecoveryPolicy.from_config(config)
    queue: asyncio.Queue = asyncio.Queue(maxsize=STREAM_BUFFER_LIMIT)

    async def receive() -> None:
        try:
            async for raw in ws:
                message = json.loads(raw)
                # Map at receipt, so REST latency doesn't become received_ts.
                payload = message.get("data", message)
                kind = payload.get("e")
                if kind == "serverShutdown":
                    raise StreamSyncError("Binance serverShutdown; resynchronize on a new connection")
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
            raise StreamSyncError("WebSocket closed; synchronization session ended")
        except Exception as exc:
            # Wake a waiting consumer; when full it checks reader.result() first.
            try:
                queue.put_nowait(exc)
            except asyncio.QueueFull:
                pass
            raise

    reader = asyncio.create_task(receive())

    async def next_event(timeout=None) -> dict:
        if reader.done():
            reader.result()
        try:
            event = await asyncio.wait_for(queue.get(), STREAM_WAIT_SECONDS if timeout is None else timeout)
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
            snapshot = await fetch_snapshot_async(
                ex["endpoints"]["rest_base_url"], symbol,
                int(ex["market_data"]["snapshot_limit"]), timeout=policy.snapshot_timeout_seconds,
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
        now = asyncio.get_running_loop().time
        last_depth = now()
        last_trade = now()
        last_status = now()
        bridge_deadline = now() + STREAM_WAIT_SECONDS
        depth_stale_seconds = ex["market_data"].get("stale_l2_ms", 2000) / 1000
        trade_stale_seconds = ex["market_data"].get("stale_trades_ms", 3000) / 1000
        while True:
            if reader.done():
                reader.result()
            deadline = min(last_depth + depth_stale_seconds, last_trade + trade_stale_seconds) if synchronized else bridge_deadline
            event = pending.popleft() if pending else await next_event(min(STREAM_WAIT_SECONDS, max(.001, deadline - now())))
            if synchronized and now() - last_depth > depth_stale_seconds:
                raise StreamSyncError("Depth feed stale while other messages continue")
            if synchronized and now() - last_trade > trade_stale_seconds:
                raise StreamSyncError("Trade feed stale while depth messages continue")
            if not synchronized and now() > bridge_deadline:
                raise StreamSyncError("Timed out waiting for depth bridge")
            if event["event_type"] == "book_delta":
                previous_id = book.last_update_id
                if event["final_update_id"] <= previous_id:
                    stale_depth_events += 1
                    continue
                if (time.monotonic_ns() - event["monotonic_ns"]) / 1e9 > depth_stale_seconds:
                    raise StreamSyncError("Buffered depth update is stale")
                book.apply_delta(event)  # Gaps still fail closed.
                last_depth = now()
                event["previous_final_update_id"] = previous_id
                depth_events += 1
                if not synchronized:
                    synchronized = True
                    write_status(config, "RUNNING", "depth_bridge_applied",
                                 last_update_id=book.last_update_id)
            else:
                trade_events += 1
                last_trade = now()
            write_event(config, event)
            written += 1
            stats = dict(written_events=written, depth_events=depth_events,
                         trade_events=trade_events, stale_depth_events=stale_depth_events,
                         gap_count=0, last_update_id=book.last_update_id)
            if synchronized and on_progress is not None:
                on_progress(stats)
            if synchronized and (written % 100 == 0 or now() - last_status >= policy.status_interval_seconds):
                write_status(config, "RUNNING", "streaming", **stats)
                last_status = now()
            # Trades alone must never qualify a synchronized-book smoke test.
            if synchronized and max_events is not None and written >= max_events:
                write_status(config, "STOPPED", "max_events_reached", **stats)
                return stats
    finally:
        reader.cancel()
        await asyncio.gather(reader, return_exceptions=True)



async def stream_session(config, max_events, *, on_progress=None):
    async with websockets.connect(
        stream_url(config), ping_interval=20, ping_timeout=10, close_timeout=5,
        open_timeout=10, max_size=STREAM_MESSAGE_MAX_BYTES, max_queue=16,
    ) as ws:
        return await collect_connected_stream(ws, config, max_events, on_progress=on_progress)


async def run_stream_async(config_path: str, max_events: int | None = None) -> int:
    config = validate_config(config_path)
    try:
        if max_events is not None and max_events < 2:
            raise ValueError("--max-events must be at least 2 (snapshot and depth bridge)")
        write_status(config, "CONNECTING", "opening_websocket")
        stats = await stream_session(config, max_events)
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
    parser.add_argument("--mode", choices=["idle", "once", "stream", "continuous"], default="idle")
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--max-events", type=int, default=None, help="Stop stream mode after N written events; useful for VPS smoke tests")
    parser.add_argument("--max-run-seconds", type=float, default=None,
                        help="Bound continuous-mode duration; otherwise run until stopped")
    args = parser.parse_args()
    if args.mode != "continuous" and args.max_run_seconds is not None:
        parser.error("--max-run-seconds belongs to continuous mode")
    if args.mode == "continuous":
        if args.max_events is not None:
            parser.error("--max-events belongs to stream smoke mode")
        from signal_desk.collector.continuous import run_continuous
        return run_continuous(args.config, args.max_run_seconds)
    if args.mode == "once":
        return run_once(args.config)
    if args.mode == "stream":
        return run_stream(args.config, max_events=args.max_events)
    return run_idle(args.config)


if __name__ == "__main__":
    raise SystemExit(main())
