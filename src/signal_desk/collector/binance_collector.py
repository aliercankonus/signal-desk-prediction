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


async def run_stream_async(config_path: str, max_events: int | None = None) -> int:
    config = validate_config(config_path)
    ex = config["exchange"]
    symbol = ex["symbol"]
    book = L2BookState()
    depth_events = 0
    trade_events = 0
    gap_count = 0

    snapshot = fetch_depth_snapshot(ex["endpoints"]["rest_base_url"], symbol, int(ex["market_data"]["snapshot_limit"]))
    snapshot_event = map_snapshot(snapshot, symbol=symbol, raw_stream="rest_depth_snapshot")
    book.apply_snapshot(snapshot_event)
    write_event(config, snapshot_event)
    write_status(config, "RUNNING", "snapshot_applied", last_update_id=book.last_update_id)

    url = stream_url(config)
    written = 1
    async with websockets.connect(url, ping_interval=20, ping_timeout=10, close_timeout=5) as ws:
        write_status(config, "RUNNING", "websocket_connected", stream_url=url, last_update_id=book.last_update_id)
        async for raw in ws:
            message = json.loads(raw)
            payload = message.get("data", message)
            event_type = payload.get("e")
            try:
                if event_type == "depthUpdate":
                    event = map_depth_delta(payload, symbol=symbol, raw_stream=message.get("stream"))
                    book.apply_delta(event)
                    event["previous_final_update_id"] = book.last_update_id
                    depth_events += 1
                    write_event(config, event)
                elif event_type == "trade":
                    event = map_trade(payload, symbol=symbol, raw_stream=message.get("stream"))
                    trade_events += 1
                    write_event(config, event)
                else:
                    continue
            except OrderBookGap as exc:
                gap_count += 1
                write_status(config, "RESYNCING", str(exc), gap_count=gap_count)
                return 2
            written += 1
            if written % 100 == 0:
                write_status(
                    config,
                    "RUNNING",
                    "streaming",
                    written_events=written,
                    depth_events=depth_events,
                    trade_events=trade_events,
                    gap_count=gap_count,
                    last_update_id=book.last_update_id,
                )
            if max_events is not None and written >= max_events:
                write_status(
                    config,
                    "STOPPED",
                    "max_events_reached",
                    written_events=written,
                    depth_events=depth_events,
                    trade_events=trade_events,
                    gap_count=gap_count,
                    last_update_id=book.last_update_id,
                )
                print(json.dumps({"status": "ok", "written_events": written, "depth_events": depth_events, "trade_events": trade_events, "gap_count": gap_count}))
                return 0
    return 0


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
