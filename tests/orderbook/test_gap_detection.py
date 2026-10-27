import pytest

from signal_desk.collector.binance_mapping import map_snapshot, map_depth_delta
from signal_desk.collector.order_book_state import L2BookState, OrderBookGap


def test_l2_book_gap_sets_resyncing():
    book = L2BookState()
    book.apply_snapshot(map_snapshot({"lastUpdateId": 100, "bids": [["10", "1"]], "asks": [["11", "1"]]}))
    gap_delta = map_depth_delta({"U": 102, "u": 105, "E": 1, "b": [], "a": []})
    with pytest.raises(OrderBookGap):
        book.apply_delta(gap_delta)
    assert book.state == "RESYNCING"


def test_l2_book_applies_contiguous_delta():
    book = L2BookState()
    book.apply_snapshot(map_snapshot({"lastUpdateId": 100, "bids": [["10", "1"]], "asks": [["11", "1"]]}))
    delta = map_depth_delta({"U": 101, "u": 101, "E": 1, "b": [["10", "2"]], "a": [["11", "0"]]})
    book.apply_delta(delta)
    assert book.top_of_book()["best_bid_qty"] == "2"
    assert book.top_of_book()["best_ask"] is None
