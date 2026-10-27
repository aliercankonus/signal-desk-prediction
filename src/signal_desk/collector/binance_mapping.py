from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def ms_to_iso(ms: int | None) -> str:
    if ms is None:
        return utc_now_iso()
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat().replace("+00:00", "Z")


def payload_hash(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def map_snapshot(snapshot: dict[str, Any], *, symbol: str = "BTCUSDT", received_ts: str | None = None, raw_stream: str | None = None) -> dict[str, Any]:
    received_ts = received_ts or utc_now_iso()
    last_update_id = int(snapshot["lastUpdateId"])
    return {
        "event_id": f"binance:{symbol}:snapshot:{last_update_id}",
        "exchange": "binance",
        "symbol": symbol,
        "product_type": "spot",
        "event_type": "book_snapshot",
        "exchange_ts": received_ts,
        "received_ts": received_ts,
        "monotonic_ns": time.monotonic_ns(),
        "first_update_id": None,
        "final_update_id": None,
        "last_update_id": last_update_id,
        "previous_final_update_id": None,
        "bids": snapshot.get("bids", []),
        "asks": snapshot.get("asks", []),
        "trade_id": None,
        "aggregate_trade_id": None,
        "trade_price": None,
        "trade_qty": None,
        "is_buyer_maker": None,
        "trade_side": None,
        "payload_hash": payload_hash(snapshot),
        "raw_stream": raw_stream,
        "data_quality": {"source": "rest_snapshot"},
    }


def map_depth_delta(delta: dict[str, Any], *, symbol: str = "BTCUSDT", raw_stream: str | None = None) -> dict[str, Any]:
    # Binance spot depth update fields: e event type, E event time, s symbol, U first update ID, u final update ID, b bids, a asks.
    first_update_id = int(delta["U"])
    final_update_id = int(delta["u"])
    exchange_ts = ms_to_iso(int(delta.get("E")))
    received_ts = utc_now_iso()
    return {
        "event_id": f"binance:{symbol}:depth:{first_update_id}:{final_update_id}",
        "exchange": "binance",
        "symbol": symbol,
        "product_type": "spot",
        "event_type": "book_delta",
        "exchange_ts": exchange_ts,
        "received_ts": received_ts,
        "monotonic_ns": time.monotonic_ns(),
        "first_update_id": first_update_id,
        "final_update_id": final_update_id,
        "last_update_id": None,
        "previous_final_update_id": None,
        "bids": delta.get("b", []),
        "asks": delta.get("a", []),
        "trade_id": None,
        "aggregate_trade_id": None,
        "trade_price": None,
        "trade_qty": None,
        "is_buyer_maker": None,
        "trade_side": None,
        "payload_hash": payload_hash(delta),
        "raw_stream": raw_stream,
        "data_quality": {"source": "ws_depth"},
    }


def map_trade(trade: dict[str, Any], *, symbol: str = "BTCUSDT", raw_stream: str | None = None) -> dict[str, Any]:
    # Binance trade stream: m=true means buyer is maker, so aggressor side is sell.
    is_buyer_maker = bool(trade.get("m"))
    side = "sell" if is_buyer_maker else "buy"
    trade_id = trade.get("t")
    exchange_ts = ms_to_iso(int(trade.get("T", trade.get("E"))))
    return {
        "event_id": f"binance:{symbol}:trade:{trade_id}",
        "exchange": "binance",
        "symbol": symbol,
        "product_type": "spot",
        "event_type": "trade",
        "exchange_ts": exchange_ts,
        "received_ts": utc_now_iso(),
        "monotonic_ns": time.monotonic_ns(),
        "first_update_id": None,
        "final_update_id": None,
        "last_update_id": None,
        "previous_final_update_id": None,
        "bids": None,
        "asks": None,
        "trade_id": trade_id,
        "aggregate_trade_id": None,
        "trade_price": trade.get("p"),
        "trade_qty": trade.get("q"),
        "is_buyer_maker": is_buyer_maker,
        "trade_side": side,
        "payload_hash": payload_hash(trade),
        "raw_stream": raw_stream,
        "data_quality": {"source": "ws_trade"},
    }
