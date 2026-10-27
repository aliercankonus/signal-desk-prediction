from signal_desk.collector.binance_mapping import map_depth_delta, map_snapshot, map_trade
from signal_desk.collector.order_book_state import L2BookState, OrderBookGap
from signal_desk.schemas.validate import validate_json


def test_snapshot_delta_and_trade_map_to_market_event_schema():
    snapshot = {"lastUpdateId": 100, "bids": [["50000.00", "1.0"]], "asks": [["50001.00", "2.0"]]}
    snap_event = map_snapshot(snapshot, received_ts="2026-10-26T00:00:00Z")
    validate_json(snap_event, "market_event.schema.json")

    delta = {"e": "depthUpdate", "E": 1792972800000, "s": "BTCUSDT", "U": 101, "u": 102, "b": [["50000.00", "1.5"]], "a": [["50001.00", "0"]]}
    delta_event = map_depth_delta(delta)
    validate_json(delta_event, "market_event.schema.json")

    trade = {"e": "trade", "E": 1792972800100, "s": "BTCUSDT", "t": 123, "p": "50000.50", "q": "0.01", "T": 1792972800100, "m": False}
    trade_event = map_trade(trade)
    validate_json(trade_event, "market_event.schema.json")
    assert trade_event["trade_side"] == "buy"


def test_order_book_gap_detection():
    book = L2BookState()
    book.apply_snapshot(map_snapshot({"lastUpdateId": 100, "bids": [["50000", "1"]], "asks": [["50010", "1"]]}, received_ts="2026-10-26T00:00:00Z"))
    book.apply_delta(map_depth_delta({"E": 1792972800000, "U": 101, "u": 101, "b": [["50001", "2"]], "a": []}))
    assert book.last_update_id == 101
    try:
        book.apply_delta(map_depth_delta({"E": 1792972800001, "U": 103, "u": 103, "b": [], "a": []}))
    except OrderBookGap:
        pass
    else:
        raise AssertionError("expected OrderBookGap")
    assert book.state == "RESYNCING"
