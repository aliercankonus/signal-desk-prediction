from __future__ import annotations

import argparse
import json
from pathlib import Path

from signal_desk.collector.order_book_state import L2BookState, OrderBookGap
from signal_desk.config.loader import validate_config
from signal_desk.features.engine import FeatureState
from signal_desk.schemas.validate import validate_json
from signal_desk.storage.jsonl import append_jsonl, iter_jsonl


def replay_events(input_path: str | Path, output_path: str | Path, *, symbol: str = "BTCUSDT") -> dict:
    book = L2BookState()
    features = FeatureState(symbol=symbol)
    stats = {"events_read": 0, "features_written": 0, "gaps": 0, "last_state": "EMPTY"}
    for event in iter_jsonl(input_path):
        stats["events_read"] += 1
        top = None
        try:
            if event.get("event_type") == "book_snapshot":
                book.apply_snapshot(event)
                top = book.top_of_book()
            elif event.get("event_type") == "book_delta":
                book.apply_delta(event)
                top = book.top_of_book()
        except OrderBookGap:
            stats["gaps"] += 1
            stats["last_state"] = book.state
            continue
        snapshot = features.update(event, top_of_book=top)
        validate_json(snapshot, "feature_snapshot.schema.json")
        append_jsonl(output_path, snapshot)
        stats["features_written"] += 1
        stats["last_state"] = book.state
    return stats


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--config", default="config/config.yaml")
    args = parser.parse_args()
    config = validate_config(args.config)
    stats = replay_events(args.input, args.output, symbol=config["exchange"]["symbol"])
    print(json.dumps(stats, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
