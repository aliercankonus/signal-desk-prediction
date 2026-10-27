from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
import hashlib
import json
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _d(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _f(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


def stable_feature_id(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "feat_" + hashlib.sha256(raw).hexdigest()[:24]


@dataclass
class FeatureState:
    symbol: str = "BTCUSDT"
    feature_version: str = "features-v15-basic-l2-trade"
    best_bid: Decimal | None = None
    best_bid_qty: Decimal | None = None
    best_ask: Decimal | None = None
    best_ask_qty: Decimal | None = None
    last_trade_price: Decimal | None = None
    last_trade_qty: Decimal | None = None
    buy_trade_qty_window: Decimal = Decimal("0")
    sell_trade_qty_window: Decimal = Decimal("0")
    event_count: int = 0
    trade_count: int = 0
    book_event_count: int = 0
    last_event_ts: str | None = None
    last_source_event_id: str | None = None

    def update(self, event: dict[str, Any], top_of_book: dict[str, Any] | None = None) -> dict[str, Any]:
        self.event_count += 1
        self.last_event_ts = event.get("exchange_ts") or event.get("received_ts") or utc_now_iso()
        self.last_source_event_id = event.get("event_id")
        if top_of_book:
            self.best_bid = _d(top_of_book.get("best_bid"))
            self.best_bid_qty = _d(top_of_book.get("best_bid_qty"))
            self.best_ask = _d(top_of_book.get("best_ask"))
            self.best_ask_qty = _d(top_of_book.get("best_ask_qty"))
            self.book_event_count += 1
        elif event.get("event_type") in {"book_snapshot", "book_delta"}:
            self.book_event_count += 1

        if event.get("event_type") == "trade":
            self.trade_count += 1
            qty = _d(event.get("trade_qty")) or Decimal("0")
            self.last_trade_price = _d(event.get("trade_price"))
            self.last_trade_qty = qty
            if event.get("trade_side") == "buy":
                self.buy_trade_qty_window += qty
            elif event.get("trade_side") == "sell":
                self.sell_trade_qty_window += qty

        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        spread = None
        midpoint = None
        imbalance = None
        if self.best_bid is not None and self.best_ask is not None:
            spread = self.best_ask - self.best_bid
            midpoint = (self.best_ask + self.best_bid) / Decimal("2")
        if self.best_bid_qty is not None and self.best_ask_qty is not None:
            denom = self.best_bid_qty + self.best_ask_qty
            if denom != 0:
                imbalance = (self.best_bid_qty - self.best_ask_qty) / denom
        trade_delta = self.buy_trade_qty_window - self.sell_trade_qty_window
        features = {
            "best_bid": _f(self.best_bid),
            "best_bid_qty": _f(self.best_bid_qty),
            "best_ask": _f(self.best_ask),
            "best_ask_qty": _f(self.best_ask_qty),
            "spread": _f(spread),
            "midpoint": _f(midpoint),
            "top_book_imbalance": _f(imbalance),
            "last_trade_price": _f(self.last_trade_price),
            "last_trade_qty": _f(self.last_trade_qty),
            "buy_qty_window": _f(self.buy_trade_qty_window),
            "sell_qty_window": _f(self.sell_trade_qty_window),
            "trade_delta_qty_window": _f(trade_delta),
            "event_count": self.event_count,
            "trade_count": self.trade_count,
            "book_event_count": self.book_event_count,
        }
        payload = {
            "asof_ts": self.last_event_ts or utc_now_iso(),
            "symbol": self.symbol,
            "feature_version": self.feature_version,
            "source_event_id": self.last_source_event_id,
            "features": features,
        }
        return {
            "feature_id": stable_feature_id(payload),
            "asof_ts": payload["asof_ts"],
            "symbol": self.symbol,
            "feature_version": self.feature_version,
            "source_event_id": self.last_source_event_id,
            "horizon_seconds": [60, 300],
            "data_quality": {"causal": True, "synthetic_window": "lifetime_until_reset", "ready": self.best_bid is not None and self.best_ask is not None},
            "features": features,
        }
