from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


class OrderBookGap(RuntimeError):
    pass


@dataclass
class L2BookState:
    last_update_id: int | None = None
    bids: dict[str, str] = field(default_factory=dict)
    asks: dict[str, str] = field(default_factory=dict)
    state: str = "EMPTY"

    def apply_snapshot(self, event: dict) -> None:
        self.last_update_id = int(event["last_update_id"])
        self.bids = {p: q for p, q in event.get("bids") or [] if Decimal(q) != 0}
        self.asks = {p: q for p, q in event.get("asks") or [] if Decimal(q) != 0}
        self.state = "READY"

    def apply_delta(self, event: dict) -> None:
        if self.last_update_id is None:
            raise OrderBookGap("Cannot apply delta before snapshot")
        first_id = int(event["first_update_id"])
        final_id = int(event["final_update_id"])
        # Binance local book rule: first event after snapshot must satisfy U <= lastUpdateId+1 <= u.
        # Subsequent events should satisfy U == lastUpdateId+1, allowing already-covered deltas to be ignored.
        expected_next = self.last_update_id + 1
        if final_id < expected_next:
            return
        if first_id > expected_next:
            self.state = "RESYNCING"
            raise OrderBookGap(f"Depth gap: expected {expected_next}, got first {first_id}")
        for side_name in ("bids", "asks"):
            book_side = getattr(self, side_name)
            for price, qty in event.get(side_name) or []:
                if Decimal(qty) == 0:
                    book_side.pop(price, None)
                else:
                    book_side[price] = qty
        self.last_update_id = final_id
        self.state = "READY"

    def top_of_book(self) -> dict[str, str | None]:
        best_bid = max(self.bids.keys(), key=Decimal) if self.bids else None
        best_ask = min(self.asks.keys(), key=Decimal) if self.asks else None
        return {
            "best_bid": best_bid,
            "best_bid_qty": self.bids.get(best_bid) if best_bid else None,
            "best_ask": best_ask,
            "best_ask_qty": self.asks.get(best_ask) if best_ask else None,
        }
