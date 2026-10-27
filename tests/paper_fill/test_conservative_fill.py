from decimal import Decimal

from signal_desk.paper.fill_model import IntervalBar, conservative_exit_fill, entry_fill_allowed


def test_conservative_stop_first_when_stop_and_target_touched():
    bar = IntervalBar(open=Decimal("100"), high=Decimal("106"), low=Decimal("98"), close=Decimal("103"))
    result = conservative_exit_fill(side="long", stop_price=Decimal("99"), take_profit_price=Decimal("105"), bar=bar)
    assert result.filled is True
    assert result.fill_price == Decimal("99")
    assert result.reason == "stop_first"


def test_entry_fill_modes_are_ordered_by_strictness():
    assert entry_fill_allowed("conservative", marketable=False, touched=True, enough_volume=True) is False
    assert entry_fill_allowed("neutral", marketable=False, touched=True, enough_volume=True) is True
    assert entry_fill_allowed("optimistic", marketable=False, touched=True, enough_volume=False) is True
