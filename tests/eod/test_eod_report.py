from pathlib import Path

from signal_desk.eod.report import generate_eod_report
from signal_desk.storage.jsonl import append_jsonl


def test_eod_report_counts_runtime_files(tmp_path: Path):
    config = {
        "project": {"mode": "paper", "execution_enabled": False},
        "exchange": {"symbol": "BTCUSDT"},
        "storage": {
            "base_path": str(tmp_path),
            "raw_path": str(tmp_path / "raw"),
            "feature_path": str(tmp_path / "features"),
            "ledger_path": str(tmp_path / "ledger"),
            "report_path": str(tmp_path / "reports"),
        },
    }
    append_jsonl(tmp_path / "raw" / "events.jsonl", {"event_id": "1"})
    append_jsonl(tmp_path / "features" / "features.jsonl", {"feature_id": "1"})
    report = generate_eod_report(config, date="2026-10-26")
    assert report["summary"]["counts"]["raw_events"] == 1
    assert report["summary"]["counts"]["features"] == 1
    assert report["data_quality"]["raw_events_present"] is True
