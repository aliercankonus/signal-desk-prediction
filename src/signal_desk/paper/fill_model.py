from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal


FillMode = Literal["conservative", "neutral", "optimistic"]


@dataclass(frozen=True)
class IntervalBar:
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


@dataclass(frozen=True)
class FillOutcome:
    filled: bool
    fill_price: Decimal | None
    reason: str


def conservative_exit_fill(*, side: Literal["long"], stop_price: Decimal, take_profit_price: Decimal, bar: IntervalBar) -> FillOutcome:
    """Conservative paper-fill exit rule.

    For a long position, if both stop and take-profit are touched inside the same interval,
    choose stop-first. This avoids overstating paper performance when intra-interval order is unknown.
    """
    if side != "long":
        raise ValueError("V0 supports long/cash-only")
    stop_touched = bar.low <= stop_price
    target_touched = bar.high >= take_profit_price
    if stop_touched:
        return FillOutcome(True, stop_price, "stop_first" if target_touched else "stop")
    if target_touched:
        return FillOutcome(True, take_profit_price, "take_profit")
    return FillOutcome(False, None, "not_touched")


def entry_fill_allowed(mode: FillMode, *, marketable: bool, touched: bool, enough_volume: bool) -> bool:
    if mode == "conservative":
        return marketable and enough_volume
    if mode == "neutral":
        return (marketable or touched) and enough_volume
    if mode == "optimistic":
        return marketable or touched
    raise ValueError(f"Unknown fill mode: {mode}")
