from signal_desk.collector.binance_mapping import map_snapshot, map_trade
from signal_desk.collector.order_book_state import L2BookState
from signal_desk.features.engine import FeatureState
from signal_desk.schemas.validate import validate_json


def test_feature_engine_emits_causal_snapshot():
    book = L2BookState()
    snapshot = map_snapshot({"lastUpdateId": 1, "bids": [["100", "2"]], "asks": [["101", "1"]]})
    book.apply_snapshot(snapshot)
    state = FeatureState()
    feat = state.update(snapshot, top_of_book=book.top_of_book())
    validate_json(feat, "feature_snapshot.schema.json")
    assert feat["features"]["spread"] == 1.0
    assert feat["data_quality"]["causal"] is True

    trade = map_trade({"t": 7, "T": 1, "p": "100.5", "q": "0.2", "m": False})
    feat2 = state.update(trade)
    assert feat2["features"]["buy_qty_window"] == 0.2
    assert feat2["features"]["trade_delta_qty_window"] == 0.2
