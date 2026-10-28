"""One bounded feature transition shared by capture and ordered offline replay."""
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import re

from signal_desk.collector.order_book_state import L2BookState, OrderBookGap
from signal_desk.features.engine import FeatureState
from signal_desk.schemas.validate import validate_json


ORDERING_VERSION = "session-applied-v1"
FEATURE_VERSION = "features-v17-applied-l2-trade"
MAX_BOOK_LEVELS = 20_000


def canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def feature_digest(snapshot):
    return hashlib.sha256(canonical_bytes(snapshot)).hexdigest()


def utc_time(value):
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("Invalid applied UTC timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("Applied timestamp must be UTC")
    return parsed.astimezone(timezone.utc)


def feature_policy(*, stale_l2_ms=2000, stale_trades_ms=3000,
                   max_book_levels=MAX_BOOK_LEVELS):
    values = {"stale_l2_ms": stale_l2_ms, "stale_trades_ms": stale_trades_ms,
              "max_book_levels": max_book_levels}
    if any(type(v) is not int or v <= 0 for v in values.values()):
        raise ValueError("Feature policy requires positive integers")
    if max_book_levels > MAX_BOOK_LEVELS:
        raise ValueError("Feature book exceeds the hard level cap")
    return values


class CausalFeaturePipeline:
    """Single-session apply order, bounded L2 state and lifetime trade totals.

    asof_ts is the recorded local application cutoff, never venue event time.
    A snapshot alone is not a synchronized/fresh book. No model or orders here.
    Any error invalidates this instance; callers must stop/discard the session.
    """
    def __init__(self, session_id, policy=None):
        if not isinstance(session_id, str) or not 1 <= len(session_id) <= 128:
            raise ValueError("Invalid collector session ID")
        self.session_id = session_id
        self.policy = feature_policy(**(policy or {}))
        self.book = L2BookState()
        self.features = FeatureState(feature_version=FEATURE_VERSION)
        self.sequence = 0
        self.applied_ns = -1
        self.applied_at = None
        self.last_trade_id = None
        self.depth_ns = self.trade_ns = None
        self.bridged = False

    def apply(self, event, *, validated=False):
        if not validated:
            validate_json(event, "market_event.schema.json")
        quality = event.get("data_quality", {})
        if (quality.get("collector_session_id") != self.session_id or
                quality.get("ordering_version") != ORDERING_VERSION or
                quality.get("feature_policy") != self.policy):
            raise ValueError("Session, ordering version or feature policy mismatch")
        seq = quality.get("ingest_sequence")
        ns = quality.get("applied_monotonic_ns")
        at = utc_time(quality.get("applied_ts"))
        if type(seq) is not int or seq != self.sequence + 1:
            raise ValueError("Missing, duplicate or reordered ingest sequence")
        if type(ns) is not int or ns <= self.applied_ns:
            raise ValueError("Applied monotonic time did not advance")
        if self.applied_at is not None and at < self.applied_at:
            raise ValueError("Applied wall clock moved backwards")
        receipt = event["monotonic_ns"]
        if receipt > ns:
            raise ValueError("Event receipt occurs after application")
        if utc_time(event["received_ts"]) > at:
            raise ValueError("Receipt wall clock occurs after application")
        utc_time(event["exchange_ts"])
        kind = event["event_type"]
        if seq == 1 and kind != "book_snapshot":
            raise ValueError("Session must start with a snapshot")
        top = None
        if kind in {"book_snapshot", "book_delta"}:
            for side in ("bids", "asks"):
                levels = event.get(side)
                if not isinstance(levels, list) or len(levels) > self.policy["max_book_levels"]:
                    raise ValueError("Missing or oversized depth levels")
                for price, qty in levels:
                    if len(price) > 64 or len(qty) > 64 or Decimal(price) <= 0 or Decimal(qty) < 0:
                        raise ValueError("Invalid or oversized depth decimal")
            if kind == "book_snapshot":
                if seq != 1 or type(event.get("last_update_id")) is not int:
                    raise ValueError("Repeated or invalid session snapshot")
                self.book.apply_snapshot(event)
            else:
                first, final = event.get("first_update_id"), event.get("final_update_id")
                if (type(first) is not int or type(final) is not int or first > final or
                        self.book.last_update_id is None or final <= self.book.last_update_id or
                        event.get("previous_final_update_id") != self.book.last_update_id):
                    raise ValueError("Invalid, stale or discontinuous depth IDs")
                self.book.apply_delta(event)
                self.bridged = True
            if len(self.book.bids) + len(self.book.asks) > self.policy["max_book_levels"]:
                raise ValueError("Feature book level cap reached")
            top = self.book.top_of_book()
            if (top["best_bid"] is not None and top["best_ask"] is not None and
                    Decimal(top["best_bid"]) >= Decimal(top["best_ask"])):
                raise ValueError("Crossed or locked book")
            self.depth_ns = receipt
        elif kind == "trade":
            trade_id = event.get("trade_id")
            if (isinstance(trade_id, bool) or not re.fullmatch(r"[0-9]{1,24}", str(trade_id)) or
                    (self.last_trade_id is not None and int(trade_id) <= self.last_trade_id)):
                raise ValueError("Invalid, duplicate or reordered trade ID")
            for key in ("trade_price", "trade_qty"):
                value = event.get(key)
                if not isinstance(value, str) or len(value) > 64 or Decimal(value) <= 0:
                    raise ValueError("Invalid trade decimal")
            maker = event.get("is_buyer_maker")
            if type(maker) is not bool or event.get("trade_side") != ("sell" if maker else "buy"):
                raise ValueError("Trade side disagrees with maker flag")
            self.last_trade_id = int(trade_id)
            self.trade_ns = receipt
        else:
            raise ValueError("Unsupported event in ordered feature pipeline")
        snapshot = self.features.update({**event, "exchange_ts": quality["applied_ts"]}, top)
        ready = (self.bridged and self.depth_ns is not None and self.trade_ns is not None and
                 ns - self.depth_ns <= self.policy["stale_l2_ms"] * 1_000_000 and
                 ns - self.trade_ns <= self.policy["stale_trades_ms"] * 1_000_000 and
                 snapshot["data_quality"]["ready"])
        snapshot["data_quality"].update(
            ready=bool(ready), collector_session_id=self.session_id, ingest_sequence=seq,
            ordering_version=ORDERING_VERSION, clock="local_application_cutoff")
        validate_json(snapshot, "feature_snapshot.schema.json")
        # Also refuse nonfinite feature output before anything is persisted.
        canonical_bytes(snapshot)
        self.sequence, self.applied_ns, self.applied_at = seq, ns, at
        return snapshot
