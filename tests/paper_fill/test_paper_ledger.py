"""Synthetic paper-only storage tests: no exchange connection or real PnL."""
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from decimal import Decimal, localcontext
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from signal_desk.paper.ledger import (PaperLedger, IntentRequest, DuplicateConflict,
    StalePortfolio, StaleWriter, BudgetExceeded, PaperStorageError, Halted)


def request(*, signal_id="sig-1", portfolio_version=0):
    # Synthetic BTC/USDT price, quantity, cash and risk; not a fee estimate.
    return IntentRequest(
        strategy_id="synthetic-strategy", signal_id=signal_id,
        feature_snapshot_id="synthetic-feature", decision_id="synthetic-decision",
        config_version="synthetic-config", plan_hash="synthetic-plan-hash",
        portfolio_version=portfolio_version, decision_time="2026-10-29T12:00:00Z",
        valid_until="2026-10-29T12:00:30Z", expires_at="2026-10-29T12:01:00Z",
        qty_btc="0.1", price_ceiling_usdt_per_btc="200", fee_buffer_usdt="1",
        risk_reserve_usdt="2")


def test_atomic_reservation_duplicate_and_restart_restore_pending_outbox(tmp_path):
    path = tmp_path / "paper.sqlite3"
    store = PaperLedger.create(path, cash_usdt="100", risk_budget_usdt="5")
    epoch = store.claim_writer("writer-A", expected_epoch=0)
    first = store.reserve(request(), writer_id="writer-A", writer_epoch=epoch)
    assert first["duplicate"] is False
    assert store.snapshot()["cash_reserved_usdt"] == "21"
    assert store.snapshot()["risk_reserved_usdt"] == "2"
    assert store.snapshot()["portfolio_version"] == 1
    assert len(store.pending_outbox(writer_id="writer-A", writer_epoch=epoch)) == 1
    assert store.reserve(request(), writer_id="writer-A", writer_epoch=epoch) == {
        **first, "duplicate": True}
    assert len(store.ledger_entries(writer_id="writer-A", writer_epoch=epoch)) == 2
    with pytest.raises(DuplicateConflict):
        store.reserve(replace(request(), fee_buffer_usdt="2"), writer_id="writer-A", writer_epoch=epoch)
    store.close()
    restored = PaperLedger.open(path)
    assert restored.snapshot()["cash_reserved_usdt"] == "21"
    assert restored.snapshot()["portfolio_version"] == 1
    takeover = restored.claim_writer("writer-B", expected_epoch=epoch)
    assert restored.pending_outbox(writer_id="writer-B", writer_epoch=takeover) == [first["outbox"]]
    assert len(restored.ledger_entries(writer_id="writer-B", writer_epoch=takeover)) == 2
    restored.close()


def test_concurrent_reservation_serializes_budget_and_portfolio_version(tmp_path):
    path = tmp_path / "paper.sqlite3"
    store = PaperLedger.create(path, cash_usdt="100", risk_budget_usdt="3")
    epoch = store.claim_writer("writer-A", expected_epoch=0)
    store.close()

    def attempt(signal):
        opened = PaperLedger.open(path)
        try:
            return opened.reserve(request(signal_id=signal), writer_id="writer-A", writer_epoch=epoch)
        finally:
            opened.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt, signal) for signal in ("sig-1", "sig-2")]
        successes = [f.result() for f in futures if f.exception() is None]
        failures = [f.exception() for f in futures if f.exception() is not None]
    assert len(successes) == 1 and len(failures) == 1
    assert isinstance(failures[0], StalePortfolio)
    opened = PaperLedger.open(path)
    assert opened.snapshot()["cash_reserved_usdt"] == "21"
    assert len(opened.pending_outbox(writer_id="writer-A", writer_epoch=epoch)) == 1
    with pytest.raises(BudgetExceeded):
        opened.reserve(request(signal_id="sig-3", portfolio_version=1),
                       writer_id="writer-A", writer_epoch=epoch)
    assert len(opened.ledger_entries(writer_id="writer-A", writer_epoch=epoch)) == 2
    opened.close()


def test_explicit_writer_fence_and_stale_portfolio_block_new_risk(tmp_path):
    path = tmp_path / "paper.sqlite3"
    first = PaperLedger.create(path, cash_usdt="100", risk_budget_usdt="5")
    epoch = first.claim_writer("writer-A", expected_epoch=0)
    second = PaperLedger.open(path)
    new_epoch = second.claim_writer("writer-B", expected_epoch=epoch)
    with pytest.raises(StaleWriter):
        first.reserve(request(), writer_id="writer-A", writer_epoch=epoch)
    with pytest.raises(StaleWriter):
        first.claim_writer("writer-A", expected_epoch=epoch)
    second.reserve(request(), writer_id="writer-B", writer_epoch=new_epoch)
    with pytest.raises(StalePortfolio):
        second.reserve(request(signal_id="sig-new"), writer_id="writer-B", writer_epoch=new_epoch)
    assert second.snapshot()["portfolio_version"] == 1
    first.close(); second.close()


def test_stale_writer_cannot_read_sendable_outbox_after_fence_transfer(tmp_path):
    path = tmp_path / "paper.sqlite3"
    first = PaperLedger.create(path, cash_usdt="100", risk_budget_usdt="5")
    epoch = first.claim_writer("writer-A", expected_epoch=0)
    first.reserve(request(), writer_id="writer-A", writer_epoch=epoch)
    second = PaperLedger.open(path)
    new_epoch = second.claim_writer("writer-B", expected_epoch=epoch)
    with pytest.raises(StaleWriter):
        first.pending_outbox(writer_id="writer-A", writer_epoch=epoch)
    with pytest.raises(StaleWriter):
        first.ledger_entries(writer_id="writer-A", writer_epoch=epoch)
    assert len(second.pending_outbox(writer_id="writer-B", writer_epoch=new_epoch)) == 1
    first.close(); second.close()


def test_simulated_write_failure_rolls_back_and_halts_until_reopen(tmp_path, monkeypatch):
    path = tmp_path / "paper.sqlite3"
    store = PaperLedger.create(path, cash_usdt="100", risk_budget_usdt="5")
    epoch = store.claim_writer("writer-A", expected_epoch=0)
    append = store._append_ledger
    def fail_second(*, kind, **kwargs):
        if kind == "risk_reserved":
            raise OSError("synthetic write failure")
        return append(kind=kind, **kwargs)
    monkeypatch.setattr(store, "_append_ledger", fail_second)
    with pytest.raises(PaperStorageError, match="new risk blocked"):
        store.reserve(request(), writer_id="writer-A", writer_epoch=epoch)
    with pytest.raises(Halted):
        store.reserve(request(signal_id="sig-2"), writer_id="writer-A", writer_epoch=epoch)
    with pytest.raises(Halted):
        store.pending_outbox(writer_id="writer-A", writer_epoch=epoch)
    store.close()
    restored = PaperLedger.open(path)
    assert restored.snapshot()["portfolio_version"] == 0
    takeover = restored.claim_writer("writer-B", expected_epoch=epoch)
    assert restored.pending_outbox(writer_id="writer-B", writer_epoch=takeover) == []
    assert restored.ledger_entries(writer_id="writer-B", writer_epoch=takeover) == []
    restored.close()


def test_process_crash_before_commit_recovers_without_outbox(tmp_path):
    path = tmp_path / "paper.sqlite3"
    store = PaperLedger.create(path, cash_usdt="100", risk_budget_usdt="5")
    epoch = store.claim_writer("writer-A", expected_epoch=0)
    store.close()
    child = """import json,os,sys
from signal_desk.paper.ledger import PaperLedger,IntentRequest
store=PaperLedger.open(sys.argv[1])
original=store._append_ledger
def crash(**kwargs):
    original(**kwargs)
    os._exit(31)
store._append_ledger=crash
store.reserve(IntentRequest(**json.loads(sys.argv[2])),writer_id='writer-A',writer_epoch=int(sys.argv[3]))
"""
    result = subprocess.run([sys.executable, "-c", child, str(path),
        json.dumps(asdict(request())), str(epoch)], capture_output=True)
    assert result.returncode == 31, result.stderr
    restored = PaperLedger.open(path)
    assert restored.snapshot()["portfolio_version"] == 0
    new_epoch = restored.claim_writer("writer-B", expected_epoch=epoch)
    assert restored.pending_outbox(writer_id="writer-B", writer_epoch=new_epoch) == []
    assert restored.ledger_entries(writer_id="writer-B", writer_epoch=new_epoch) == []
    restored.reserve(request(), writer_id="writer-B", writer_epoch=new_epoch)
    restored.close()


@pytest.mark.parametrize("field,value", [("qty_btc", "NaN"), ("qty_btc", "-1"),
    ("price_ceiling_usdt_per_btc", "1e3"), ("fee_buffer_usdt", 0.1),
    ("decision_time", "2026-10-29T12:00:00+02:00")])
def test_bad_decimal_or_time_fails_before_any_write(tmp_path, field, value):
    path = tmp_path / "paper.sqlite3"
    store = PaperLedger.create(path, cash_usdt="100", risk_budget_usdt="5")
    epoch = store.claim_writer("writer-A", expected_epoch=0)
    with pytest.raises(ValueError):
        store.reserve(replace(request(), **{field: value}), writer_id="writer-A", writer_epoch=epoch)
    assert store.ledger_entries(writer_id="writer-A", writer_epoch=epoch) == [] and store.pending_outbox(writer_id="writer-A", writer_epoch=epoch) == []
    store.close()


def test_exact_decimal_product_does_not_round_cash_reservation(tmp_path):
    store = PaperLedger.create(tmp_path / "paper.sqlite3", cash_usdt="100", risk_budget_usdt="5")
    epoch = store.claim_writer("writer-A", expected_epoch=0)
    req = replace(request(), qty_btc="0.12345678",
                  price_ceiling_usdt_per_btc="1.23456789", fee_buffer_usdt="0.00000001")
    store.reserve(req, writer_id="writer-A", writer_epoch=epoch)
    expected = Decimal(req.qty_btc) * Decimal(req.price_ceiling_usdt_per_btc) + Decimal(req.fee_buffer_usdt)
    assert Decimal(store.snapshot()["cash_reserved_usdt"]) == expected
    store.close()


def test_ambient_decimal_precision_cannot_underreserve_synthetic_cash(tmp_path):
    store = PaperLedger.create(tmp_path / "paper.sqlite3", cash_usdt="20", risk_budget_usdt="5")
    epoch = store.claim_writer("writer-A", expected_epoch=0)
    with localcontext() as ctx:
        ctx.prec = 1
        with pytest.raises(BudgetExceeded):
            store.reserve(replace(request(), qty_btc="0.11", fee_buffer_usdt="0"),
                          writer_id="writer-A", writer_epoch=epoch)
    assert store.snapshot()["portfolio_version"] == 0
    store.close()


def test_interrupted_write_never_exposes_uncommitted_outbox(tmp_path, monkeypatch):
    path = tmp_path / "paper.sqlite3"
    store = PaperLedger.create(path, cash_usdt="100", risk_budget_usdt="5")
    epoch = store.claim_writer("writer-A", expected_epoch=0)
    def interrupt(**kwargs):
        raise KeyboardInterrupt("synthetic interrupt before commit")
    monkeypatch.setattr(store, "_append_ledger", interrupt)
    with pytest.raises(KeyboardInterrupt):
        store.reserve(request(), writer_id="writer-A", writer_epoch=epoch)
    with pytest.raises(Halted):
        store.pending_outbox(writer_id="writer-A", writer_epoch=epoch)
    store.close()
    restored = PaperLedger.open(path)
    takeover = restored.claim_writer("writer-B", expected_epoch=epoch)
    assert restored.pending_outbox(writer_id="writer-B", writer_epoch=takeover) == []
    assert restored.snapshot()["portfolio_version"] == 0
    restored.close()


def test_recovery_reads_one_snapshot_during_concurrent_commit(tmp_path, monkeypatch):
    path = tmp_path / "paper.sqlite3"
    writer = PaperLedger.create(path, cash_usdt="100", risk_budget_usdt="5")
    epoch = writer.claim_writer("writer-A", expected_epoch=0)
    original = PaperLedger._meta
    interleaved = []
    def interleave_once(self):
        row = original(self)
        if self is not writer and not interleaved:
            interleaved.append(True)
            writer.reserve(request(), writer_id="writer-A", writer_epoch=epoch)
        return row
    monkeypatch.setattr(PaperLedger, "_meta", interleave_once)
    restored = PaperLedger.open(path)
    assert interleaved == [True]
    assert restored.snapshot()["portfolio_version"] == 1
    takeover = restored.claim_writer("writer-B", expected_epoch=epoch)
    assert len(restored.ledger_entries(writer_id="writer-B", writer_epoch=takeover)) == 2
    writer.close(); restored.close()


def test_write_refuses_trigger_removed_after_open(tmp_path):
    path = tmp_path / "paper.sqlite3"
    store = PaperLedger.create(path, cash_usdt="100", risk_budget_usdt="5")
    epoch = store.claim_writer("writer-A", expected_epoch=0)
    with sqlite3.connect(path) as raw:
        raw.execute("DROP TRIGGER ledger_no_update")
    with pytest.raises(PaperStorageError, match="uncertain"):
        store.reserve(request(), writer_id="writer-A", writer_epoch=epoch)
    with pytest.raises(Halted):
        store.reserve(request(), writer_id="writer-A", writer_epoch=epoch)
    store.close()


@pytest.mark.parametrize("trigger", ["ledger_no_update", "ledger_no_delete",
    "intent_no_delete", "reservation_no_delete", "outbox_no_delete"])
@pytest.mark.parametrize("replacement", [False, True])
def test_recovery_rejects_missing_or_weakened_append_only_trigger(tmp_path, trigger, replacement):
    path = tmp_path / "paper.sqlite3"
    store = PaperLedger.create(path, cash_usdt="100", risk_budget_usdt="5")
    store.close()
    with sqlite3.connect(path) as raw:
        raw.execute(f"DROP TRIGGER {trigger}")  # fixed synthetic test identifiers only
        if replacement:
            raw.execute(f"CREATE TRIGGER {trigger} BEFORE DELETE ON ledger BEGIN SELECT 1; END")
    with pytest.raises(PaperStorageError, match="trigger"):
        PaperLedger.open(path)


def test_recovery_rejects_materialized_content_different_from_ledger(tmp_path):
    path = tmp_path / "paper.sqlite3"
    store = PaperLedger.create(path, cash_usdt="100", risk_budget_usdt="5")
    epoch = store.claim_writer("writer-A", expected_epoch=0)
    store.reserve(request(), writer_id="writer-A", writer_epoch=epoch)
    iid, content = store._conn.execute("SELECT intent_id,content FROM intents").fetchone()
    altered = json.loads(content)
    altered["risk_reserve_usdt"] = "3"
    from signal_desk.paper.ledger import _digest, _json
    store._conn.execute("UPDATE intents SET content=?,fingerprint=? WHERE intent_id=?",
                        (_json(altered), _digest(altered), iid))
    store.close()
    with pytest.raises(PaperStorageError, match="Intent differs from ledger"):
        PaperLedger.open(path)


def test_storage_bound_failure_latches_halt_even_after_transient_clear(tmp_path, monkeypatch):
    store = PaperLedger.create(tmp_path / "paper.sqlite3", cash_usdt="100", risk_budget_usdt="5")
    epoch = store.claim_writer("writer-A", expected_epoch=0)
    original = store._bounds
    def out_of_space():
        raise PaperStorageError("synthetic resource bound")
    monkeypatch.setattr(store, "_bounds", out_of_space)
    with pytest.raises(PaperStorageError):
        store.reserve(request(), writer_id="writer-A", writer_epoch=epoch)
    monkeypatch.setattr(store, "_bounds", original)
    with pytest.raises(Halted):
        store.reserve(request(), writer_id="writer-A", writer_epoch=epoch)
    store.close()


def test_intent_count_bound_blocks_without_deleting_pending_records(tmp_path, monkeypatch):
    store = PaperLedger.create(tmp_path / "paper.sqlite3", cash_usdt="100", risk_budget_usdt="5")
    epoch = store.claim_writer("writer-A", expected_epoch=0)
    store.reserve(request(), writer_id="writer-A", writer_epoch=epoch)
    monkeypatch.setattr("signal_desk.paper.ledger.MAX_INTENTS", 1)
    with pytest.raises(BudgetExceeded, match="resource bound"):
        store.reserve(request(signal_id="sig-2", portfolio_version=1),
                      writer_id="writer-A", writer_epoch=epoch)
    assert len(store.pending_outbox(writer_id="writer-A", writer_epoch=epoch)) == 1 and len(store.ledger_entries(writer_id="writer-A", writer_epoch=epoch)) == 2
    store.close()
