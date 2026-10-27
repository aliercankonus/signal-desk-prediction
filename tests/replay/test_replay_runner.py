from pathlib import Path

from signal_desk.collector.binance_mapping import map_snapshot, map_depth_delta, map_trade
from signal_desk.replay.runner import replay_events
from signal_desk.storage.jsonl import append_jsonl, read_jsonl


def test_replay_writes_feature_snapshots(tmp_path: Path):
    raw = tmp_path / "raw.jsonl"
    out = tmp_path / "features.jsonl"
    append_jsonl(raw, map_snapshot({"lastUpdateId": 10, "bids": [["100", "1"]], "asks": [["101", "1"]]}))
    append_jsonl(raw, map_depth_delta({"U": 11, "u": 11, "E": 1, "b": [["100", "2"]], "a": []}))
    append_jsonl(raw, map_trade({"t": 1, "T": 1, "p": "100.5", "q": "0.1", "m": True}))
    stats = replay_events(raw, out)
    rows = read_jsonl(out)
    assert stats["events_read"] == 3
    assert stats["features_written"] == 3
    assert rows[-1]["features"]["sell_qty_window"] == 0.1
