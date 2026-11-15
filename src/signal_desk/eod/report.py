from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from signal_desk.config.loader import validate_config
from signal_desk.schemas.validate import validate_json


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("rb") as f:
        return sum(1 for line in f if line.strip())


_DATE_IN_NAME = re.compile(r"\d{4}-\d{2}-\d{2}")


def _iter_jsonl_files(path: Path, date: str | None = None) -> Iterable[Path]:
    if not path.exists():
        return []
    files = (p for p in path.rglob("*.jsonl") if p.is_file())
    if date is not None:
        # Day-partitioned files (e.g. binance_btcusdt_depth_YYYY-MM-DD.jsonl) count only for their own date.
        files = (p for p in files if date in _DATE_IN_NAME.findall(p.name) or not _DATE_IN_NAME.search(p.name))
    return sorted(files)


def generate_eod_report(config: dict, *, date: str, revision: int = 1) -> dict:
    base = Path(config["storage"]["base_path"])
    raw_count = sum(_count_jsonl(p) for p in _iter_jsonl_files(Path(config["storage"]["raw_path"]), date))
    feature_count = sum(_count_jsonl(p) for p in _iter_jsonl_files(Path(config["storage"]["feature_path"]), date))
    ledger_count = sum(_count_jsonl(p) for p in _iter_jsonl_files(Path(config["storage"]["ledger_path"]), date))
    report_base = {
        "date": date,
        "revision": revision,
        "symbol": config["exchange"]["symbol"],
        "counts": {"raw_events": raw_count, "features": feature_count, "ledger_entries": ledger_count},
    }
    report_id = "eod_" + hashlib.sha256(json.dumps(report_base, sort_keys=True).encode()).hexdigest()[:20]
    payload = {
        "report_id": report_id,
        "date": date,
        "revision": revision,
        "symbol": config["exchange"]["symbol"],
        "summary": {
            "mode": config["project"]["mode"],
            "execution_enabled": config["project"]["execution_enabled"],
            "counts": report_base["counts"],
        },
        "data_quality": {
            "raw_events_present": raw_count > 0,
            "features_present": feature_count > 0,
            "ledger_present": ledger_count > 0,
            "notes": "skeleton EOD counts only; no PnL or model evaluation yet",
        },
        "strategy_results": {},
        "model_results": {},
        "paper_results": {},
        "alarms": [],
        "generated_ts": utc_now_iso(),
    }
    validate_json(payload, "eod_report.schema.json")
    return payload


def write_report(config: dict, report: dict) -> Path:
    out_dir = Path(config["storage"]["report_path"])
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{report['date']}-rev{report['revision']}.json"
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    parser.add_argument("--revision", type=int, default=1)
    args = parser.parse_args()
    config = validate_config(args.config)
    report = generate_eod_report(config, date=args.date, revision=args.revision)
    out = write_report(config, report)
    print(json.dumps({"report_path": str(out), "report_id": report["report_id"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
