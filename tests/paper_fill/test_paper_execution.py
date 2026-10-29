"""Synthetic, explicitly observed local-paper execution accounting tests."""
from decimal import Decimal, localcontext
from datetime import datetime, timedelta, timezone

import pytest
import sqlite3
import json
import subprocess
import sys
import threading

from signal_desk.paper.ledger import (
    PaperLedger, IntentRequest, DuplicateConflict, StaleWriter, ClaimUnavailable,
    PaperStorageError, Halted, ReconciliationRequired, BudgetExceeded,
)
from signal_desk.paper.local_receiver import LocalPaperReceiver


def at(seconds):
    return (datetime(2026, 10, 29, 12, tzinfo=timezone.utc) +
            timedelta(seconds=seconds)).isoformat(timespec="seconds").replace("+00:00", "Z")


def fixture(tmp_path):
    path = tmp_path / "synthetic-paper.sqlite3"
    ledger = PaperLedger.create(path, cash_usdt="100", risk_budget_usdt="5")
    epoch = ledger.claim_writer("writer-A", expected_epoch=0)
    request = IntentRequest(
        strategy_id="synthetic", signal_id="synthetic-signal", feature_snapshot_id="synthetic-feature",
        decision_id="synthetic-decision", config_version="synthetic-config", plan_hash="synthetic-plan",
        portfolio_version=0, decision_time=at(0), valid_until=at(60), expires_at=at(120),
        qty_btc="0.1", price_ceiling_usdt_per_btc="200", fee_buffer_usdt="1",
        risk_reserve_usdt="2")
    reserved = ledger.reserve(request, writer_id="writer-A", writer_epoch=epoch)
    envelope = ledger.claim_outbox(reserved["intent_id"], claim_id="synthetic-claim", claim_version=1,
        claimed_at=at(1), writer_id="writer-A", writer_epoch=epoch)
    with LocalPaperReceiver(path) as receiver:
        receipt = receiver.accept(envelope, accepted_at=at(2))
    ledger.ack_receipt(reserved["intent_id"], receipt["receipt_id"],
        acked_at=at(3), writer_id="writer-A", writer_epoch=epoch)
    return path, ledger, epoch, reserved["intent_id"]


def fill(intent_id, *, fill_id="synthetic-fill-1", delta="0.04", cumulative="0.04", fee="0.08", when=4):
    # All execution prices, fees and quantities are synthetic fixture values.
    return {"fill_id": fill_id, "intent_id": intent_id, "fill_ts": at(when),
            "delta_qty_btc": delta, "cumulative_qty_btc": cumulative,
            "price_usdt_per_btc": "200", "fee_usdt": fee,
            "source_kind": "already_observed_local_paper",
            "mode": "neutral", "fill_reason": "manual_reconcile",
            "assumptions": ["synthetic previously observed local-paper fill; not inferred from market data"]}


def test_recording_requires_already_observed_source_not_price_touch_generation(tmp_path):
    path, ledger, epoch, iid = fixture(tmp_path)
    with pytest.raises(ValueError):
        ledger.record_observed_fill({**fill(iid), "source_kind": "generated_from_price_touch"},
            writer_id="writer-A", writer_epoch=epoch)
    assert ledger.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch)["filled_qty_btc"] == "0"
    ledger.close()


def test_40_percent_fill_then_confirmed_cancel_preserves_exposure(tmp_path):
    path, ledger, epoch, iid = fixture(tmp_path)
    first = ledger.record_observed_fill(fill(iid), writer_id="writer-A", writer_epoch=epoch)
    assert first["status"] == "PARTIALLY_FILLED"
    state = ledger.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch)
    assert state["filled_qty_btc"] == "0.04" and state["remaining_qty_btc"] == "0.06"
    assert state["actual_cash_usdt"] == "91.92" and state["actual_base_btc"] == "0.04"
    assert state["cash_reserved_usdt"] == "12.6" and state["risk_reserved_usdt"] == "1.2"
    assert state["filled_risk_exposure_usdt"] == "0.8"
    assert state["available_cash_usdt"] == "79.32"
    pending = ledger.request_cancel(iid, cancel_id="synthetic-cancel", requested_at=at(5),
        writer_id="writer-A", writer_epoch=epoch)
    assert pending["status"] == "CANCEL_PENDING"
    assert ledger.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch)["cash_reserved_usdt"] == "12.6"
    confirmed = ledger.confirm_cancel(iid, cancel_id="synthetic-cancel", confirmed_at=at(6),
        writer_id="writer-A", writer_epoch=epoch)
    assert confirmed["status"] == "CANCELLED"
    state = ledger.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch)
    assert state["filled_qty_btc"] == "0.04" and state["cancelled_qty_btc"] == "0.06"
    assert state["remaining_qty_btc"] == "0"
    assert state["actual_cash_usdt"] == "91.92" and state["actual_base_btc"] == "0.04"
    assert state["cash_reserved_usdt"] == "0" and state["risk_reserved_usdt"] == "0"
    assert state["filled_risk_exposure_usdt"] == "0.8"
    assert state["available_cash_usdt"] == "91.92"
    ledger.close()


def test_cancel_pending_fill_is_accounted_once_before_confirmation(tmp_path):
    path, ledger, epoch, iid = fixture(tmp_path)
    first = fill(iid)
    ledger.record_observed_fill(first, writer_id="writer-A", writer_epoch=epoch)
    ledger.request_cancel(iid, cancel_id="synthetic-cancel", requested_at=at(5),
        writer_id="writer-A", writer_epoch=epoch)
    second = fill(iid, fill_id="synthetic-fill-2", delta="0.02", cumulative="0.06", fee="0.04", when=6)
    assert ledger.record_observed_fill(second, writer_id="writer-A", writer_epoch=epoch)["status"] == "CANCEL_PENDING"
    assert ledger.record_observed_fill(second, writer_id="writer-A", writer_epoch=epoch)["status"] == "CANCEL_PENDING"
    pending = ledger.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch)
    assert pending["filled_qty_btc"] == "0.06" and pending["remaining_qty_btc"] == "0.04"
    assert pending["cash_reserved_usdt"] == "8.4" and pending["risk_reserved_usdt"] == "0.8"
    assert pending["actual_cash_usdt"] == "87.88" and pending["fees_usdt"] == "0.12"
    ledger.confirm_cancel(iid, cancel_id="synthetic-cancel", confirmed_at=at(7),
        writer_id="writer-A", writer_epoch=epoch)
    final = ledger.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch)
    assert final["filled_qty_btc"] == "0.06" and final["cancelled_qty_btc"] == "0.04"
    assert final["actual_base_btc"] == "0.06" and final["filled_risk_exposure_usdt"] == "1.2"
    assert final["cash_reserved_usdt"] == "0" and final["actual_cash_usdt"] == "87.88"
    ledger.close()
    reopened = PaperLedger.open(path)
    assert reopened.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch) == final
    reopened.close()


def test_identical_duplicate_and_conflicting_or_bad_cumulative_fill(tmp_path):
    path, ledger, epoch, iid = fixture(tmp_path)
    first = fill(iid)
    result = ledger.record_observed_fill(first, writer_id="writer-A", writer_epoch=epoch)
    assert ledger.record_observed_fill(first, writer_id="writer-A", writer_epoch=epoch) == result
    before = ledger.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch)
    with pytest.raises(DuplicateConflict):
        ledger.record_observed_fill({**first, "fee_usdt": "0.09"}, writer_id="writer-A", writer_epoch=epoch)
    with pytest.raises(DuplicateConflict):
        ledger.record_observed_fill(fill(iid, fill_id="synthetic-fill-2", delta="0.02", cumulative="0.04"),
            writer_id="writer-A", writer_epoch=epoch)
    with pytest.raises(DuplicateConflict):
        ledger.record_observed_fill(fill(iid, fill_id="synthetic-fill-3", delta="0.07", cumulative="0.11"),
            writer_id="writer-A", writer_epoch=epoch)
    assert ledger.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch) == before
    ledger.close()
    reopened = PaperLedger.open(path)
    assert reopened.record_observed_fill(first, writer_id="writer-A", writer_epoch=epoch) == result
    assert reopened.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch) == before
    reopened.close()


def test_writer_takeover_fences_fills_and_execution_reads(tmp_path):
    path, old, epoch, iid = fixture(tmp_path)
    newer = PaperLedger.open(path)
    new_epoch = newer.claim_writer("writer-B", expected_epoch=epoch)
    with pytest.raises(StaleWriter):
        old.record_observed_fill(fill(iid), writer_id="writer-A", writer_epoch=epoch)
    with pytest.raises(StaleWriter):
        old.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch)
    assert newer.record_observed_fill(fill(iid), writer_id="writer-B", writer_epoch=new_epoch)["status"] == "PARTIALLY_FILLED"
    old.close(); newer.close()
    recovered = PaperLedger.open(path)
    assert recovered.execution_snapshot(iid, writer_id="writer-B", writer_epoch=new_epoch)["filled_qty_btc"] == "0.04"
    recovered.close()


@pytest.mark.parametrize("observed_event_second", [1, 7])
def test_terminal_late_correction_is_durable_incident_without_inventory_change(tmp_path, observed_event_second):
    path, ledger, epoch, iid = fixture(tmp_path)
    ledger.record_observed_fill(fill(iid), writer_id="writer-A", writer_epoch=epoch)
    ledger.request_cancel(iid, cancel_id="synthetic-cancel", requested_at=at(5),
        writer_id="writer-A", writer_epoch=epoch)
    ledger.confirm_cancel(iid, cancel_id="synthetic-cancel", confirmed_at=at(6),
        writer_id="writer-A", writer_epoch=epoch)
    before = ledger.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch)
    correction = fill(iid, fill_id="late-correction", delta="0.02", cumulative="0.06", fee="0.04", when=observed_event_second)
    incident = ledger.record_observed_fill(correction, writer_id="writer-A", writer_epoch=epoch)
    assert incident["status"] == "RECONCILIATION_INCIDENT"
    assert ledger.record_observed_fill(correction, writer_id="writer-A", writer_epoch=epoch) == incident
    with pytest.raises(DuplicateConflict):
        ledger.record_observed_fill({**correction, "fee_usdt": "0.05"}, writer_id="writer-A", writer_epoch=epoch)
    assert ledger.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch) == before
    assert len(ledger.pending_incidents(writer_id="writer-A", writer_epoch=epoch)) == 1
    new_request = IntentRequest(
        strategy_id="synthetic", signal_id="another", feature_snapshot_id="synthetic-feature",
        decision_id="synthetic-decision", config_version="synthetic-config", plan_hash="synthetic-plan",
        portfolio_version=1, decision_time=at(10), valid_until=at(60), expires_at=at(120),
        qty_btc="0.1", price_ceiling_usdt_per_btc="200", fee_buffer_usdt="1",
        risk_reserve_usdt="2")
    with pytest.raises(ReconciliationRequired):
        ledger.reserve(new_request, writer_id="writer-A", writer_epoch=epoch)
    ledger.close()
    reopened = PaperLedger.open(path)
    assert reopened.pending_incidents(writer_id="writer-A", writer_epoch=epoch) == [
        {"event": correction, "result": incident}]
    assert reopened.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch) == before
    reopened.close()


def test_explicit_v2_migration_preserves_receipt_ack_and_reservation(tmp_path):
    path, ledger, epoch, iid = fixture(tmp_path)
    receipt = ledger.reconcile_receipt(iid, writer_id="writer-A", writer_epoch=epoch)
    ledger.close()
    from signal_desk.paper.ledger import REQUIRED_TRIGGERS, V2_TRIGGERS
    with sqlite3.connect(path) as raw:
        for name in REQUIRED_TRIGGERS.keys() - V2_TRIGGERS.keys():
            raw.execute(f"DROP TRIGGER {name}")  # fixed in-repository names only
        for table in ("incidents", "cancels", "fills", "execution", "execution_meta"):
            raw.execute(f"DROP TABLE {table}")  # fixed in-repository names only
        raw.execute("UPDATE meta SET schema_version=2 WHERE id=1")
    with pytest.raises(PaperStorageError, match="migrate_v1/v2"):
        PaperLedger.open(path)
    migrated = PaperLedger.migrate_v2(path)
    assert migrated.reconcile_receipt(iid, writer_id="writer-A", writer_epoch=epoch) == receipt
    assert migrated.snapshot()["cash_reserved_usdt"] == "21"
    assert migrated.record_observed_fill(fill(iid), writer_id="writer-A", writer_epoch=epoch)["status"] == "PARTIALLY_FILLED"
    migrated.close()
    with pytest.raises(PaperStorageError, match="Only verified schema v2"):
        PaperLedger.migrate_v2(path)


def test_fill_write_failure_halts_and_reopen_has_original_reservation(tmp_path, monkeypatch):
    path, ledger, epoch, iid = fixture(tmp_path)
    def fail(**kwargs):
        raise OSError("synthetic execution ledger failure")
    monkeypatch.setattr(ledger, "_append_execution_event", fail)
    with pytest.raises(PaperStorageError):
        ledger.record_observed_fill(fill(iid), writer_id="writer-A", writer_epoch=epoch)
    with pytest.raises(Halted):
        ledger.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch)
    ledger.close()
    reopened = PaperLedger.open(path)
    state = reopened.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch)
    assert state["filled_qty_btc"] == "0" and state["cash_reserved_usdt"] == "21"
    assert reopened.snapshot()["cash_actual_usdt"] == "100"
    reopened.close()


def test_cancel_confirmation_write_failure_retains_unfilled_reservation(tmp_path, monkeypatch):
    path, ledger, epoch, iid = fixture(tmp_path)
    ledger.record_observed_fill(fill(iid), writer_id="writer-A", writer_epoch=epoch)
    ledger.request_cancel(iid, cancel_id="synthetic-cancel", requested_at=at(5),
        writer_id="writer-A", writer_epoch=epoch)
    def fail(**kwargs):
        raise OSError("synthetic cancel ledger failure")
    monkeypatch.setattr(ledger, "_append_execution_event", fail)
    with pytest.raises(PaperStorageError):
        ledger.confirm_cancel(iid, cancel_id="synthetic-cancel", confirmed_at=at(6),
            writer_id="writer-A", writer_epoch=epoch)
    ledger.close()
    reopened = PaperLedger.open(path)
    state = reopened.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch)
    assert state["status"] == "CANCEL_PENDING" and state["remaining_qty_btc"] == "0.06"
    assert reopened.snapshot()["cash_reserved_usdt"] == "12.6"
    reopened.close()


def test_crash_between_fill_state_update_and_commit_has_no_fill(tmp_path):
    path, ledger, epoch, iid = fixture(tmp_path)
    ledger.close()
    child = """import json,os,sys
from signal_desk.paper.ledger import PaperLedger
store=PaperLedger.open(sys.argv[1])
def crash(**kwargs):
    os._exit(37)
store._append_execution_event=crash
store.record_observed_fill(json.loads(sys.argv[2]),writer_id='writer-A',writer_epoch=int(sys.argv[3]))
"""
    result = subprocess.run([sys.executable, "-c", child, str(path), json.dumps(fill(iid)), str(epoch)], capture_output=True)
    assert result.returncode == 37, result.stderr
    reopened = PaperLedger.open(path)
    assert reopened.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch)["filled_qty_btc"] == "0"
    assert reopened.snapshot()["cash_reserved_usdt"] == "21"
    reopened.close()


def test_recovery_rejects_tampered_execution_totals(tmp_path):
    path, ledger, epoch, iid = fixture(tmp_path)
    ledger.record_observed_fill(fill(iid), writer_id="writer-A", writer_epoch=epoch)
    ledger.close()
    with sqlite3.connect(path) as raw:
        raw.execute("UPDATE execution_meta SET cash_actual='99' WHERE id=1")
    with pytest.raises(PaperStorageError, match="materialized portfolio"):
        PaperLedger.open(path)


def test_confirm_cancel_cannot_precede_recorded_fill_timestamp(tmp_path):
    path, ledger, epoch, iid = fixture(tmp_path)
    ledger.request_cancel(iid, cancel_id="synthetic-cancel", requested_at=at(5),
        writer_id="writer-A", writer_epoch=epoch)
    ledger.record_observed_fill(fill(iid, when=9), writer_id="writer-A", writer_epoch=epoch)
    before = ledger.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch)
    with pytest.raises(DuplicateConflict):
        ledger.confirm_cancel(iid, cancel_id="synthetic-cancel", confirmed_at=at(8),
            writer_id="writer-A", writer_epoch=epoch)
    assert ledger.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch) == before
    assert ledger.snapshot()["cash_reserved_usdt"] == "12.6"
    result = ledger.confirm_cancel(iid, cancel_id="synthetic-cancel", confirmed_at=at(9),
        writer_id="writer-A", writer_epoch=epoch)
    assert result["status"] == "CANCELLED"
    ledger.close()
    reopened = PaperLedger.open(path)
    assert reopened.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch)["filled_qty_btc"] == "0.04"
    reopened.close()


def test_snapshot_balances_independent_of_decimal_context(tmp_path):
    path, ledger, epoch, iid = fixture(tmp_path)
    ledger.record_observed_fill(fill(iid), writer_id="writer-A", writer_epoch=epoch)
    with localcontext() as ctx:
        ctx.prec = 1
        aggregate = ledger.snapshot()
        execution = ledger.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch)
    assert aggregate["cash_actual_usdt"] == "91.92"
    assert aggregate["cash_reserved_usdt"] == "12.6"
    assert aggregate["cash_available_usdt"] == "79.32"
    assert execution["available_cash_usdt"] == "79.32"
    ledger.close()


def test_snapshot_reads_one_consistent_state_when_fill_races(tmp_path, monkeypatch):
    path, ledger, epoch, iid = fixture(tmp_path)
    original_meta = ledger._meta
    threads = []
    done = threading.Event()
    errors = []
    def concurrent_fill():
        other = None
        try:
            other = PaperLedger.open(path)
            other.record_observed_fill(fill(iid), writer_id="writer-A", writer_epoch=epoch)
        except Exception as exc:
            errors.append(exc)
        finally:
            if other is not None:
                other.close()
            done.set()
    def interleave():
        state = original_meta()
        if not threads:
            worker = threading.Thread(target=concurrent_fill)
            threads.append(worker)
            worker.start()
            done.wait(1)
        return state
    monkeypatch.setattr(ledger, "_meta", interleave)
    try:
        before = ledger.snapshot()
        assert before["cash_reserved_usdt"] == "21"
        assert before["cash_actual_usdt"] == "100"
        assert before["cash_available_usdt"] == "79"
        threads[0].join(timeout=4)
        assert done.is_set() and not errors, errors
        after = ledger.snapshot()
        assert after["cash_reserved_usdt"] == "12.6"
        assert after["cash_actual_usdt"] == "91.92"
        assert after["cash_available_usdt"] == "79.32"
    finally:
        if threads:
            threads[0].join(timeout=4)
        ledger.close()


def test_cancel_request_cannot_precede_local_acceptance(tmp_path):
    path, ledger, epoch, iid = fixture(tmp_path)
    with pytest.raises(ClaimUnavailable):
        ledger.request_cancel(iid, cancel_id="early-cancel", requested_at=at(1),
            writer_id="writer-A", writer_epoch=epoch)
    state = ledger.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch)
    assert state["status"] == "OPEN" and state["cash_reserved_usdt"] == "21"
    ledger.close()


def test_cancel_idempotency_and_conflicting_confirmation(tmp_path):
    path, ledger, epoch, iid = fixture(tmp_path)
    pending = ledger.request_cancel(iid, cancel_id="synthetic-cancel", requested_at=at(4),
        writer_id="writer-A", writer_epoch=epoch)
    assert ledger.request_cancel(iid, cancel_id="synthetic-cancel", requested_at=at(4),
        writer_id="writer-A", writer_epoch=epoch) == pending
    with pytest.raises(DuplicateConflict):
        ledger.request_cancel(iid, cancel_id="different", requested_at=at(4),
            writer_id="writer-A", writer_epoch=epoch)
    with pytest.raises(DuplicateConflict):
        ledger.confirm_cancel(iid, cancel_id="synthetic-cancel", confirmed_at=at(3),
            writer_id="writer-A", writer_epoch=epoch)
    assert ledger.snapshot()["cash_reserved_usdt"] == "21"
    result = ledger.confirm_cancel(iid, cancel_id="synthetic-cancel", confirmed_at=at(5),
        writer_id="writer-A", writer_epoch=epoch)
    assert ledger.confirm_cancel(iid, cancel_id="synthetic-cancel", confirmed_at=at(5),
        writer_id="writer-A", writer_epoch=epoch) == result
    with pytest.raises(DuplicateConflict):
        ledger.confirm_cancel(iid, cancel_id="different", confirmed_at=at(5),
            writer_id="writer-A", writer_epoch=epoch)
    assert ledger.snapshot()["cash_actual_usdt"] == "100"
    ledger.close()


def test_full_fill_during_pending_cancel_retains_exposure(tmp_path):
    path, ledger, epoch, iid = fixture(tmp_path)
    ledger.record_observed_fill(fill(iid), writer_id="writer-A", writer_epoch=epoch)
    ledger.request_cancel(iid, cancel_id="synthetic-cancel", requested_at=at(5),
        writer_id="writer-A", writer_epoch=epoch)
    final_fill = fill(iid, fill_id="synthetic-fill-2", delta="0.06", cumulative="0.1", fee="0.12", when=6)
    assert ledger.record_observed_fill(final_fill, writer_id="writer-A", writer_epoch=epoch)["status"] == "CANCEL_PENDING"
    assert ledger.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch)["remaining_qty_btc"] == "0"
    assert ledger.confirm_cancel(iid, cancel_id="synthetic-cancel", confirmed_at=at(7),
        writer_id="writer-A", writer_epoch=epoch)["status"] == "FILLED"
    state = ledger.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch)
    assert state["filled_qty_btc"] == "0.1" and state["cancelled_qty_btc"] == "0"
    assert state["filled_risk_exposure_usdt"] == "2" and state["risk_reserved_usdt"] == "0"
    assert state["actual_cash_usdt"] == "79.8" and state["actual_base_btc"] == "0.1"
    ledger.close()
    reopened = PaperLedger.open(path)
    assert reopened.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch) == state
    reopened.close()


def test_observed_fill_cannot_create_negative_cash_or_inventory(tmp_path):
    path, ledger, epoch, iid = fixture(tmp_path)
    oversized = {**fill(iid), "price_usdt_per_btc": "3000"}
    with pytest.raises(BudgetExceeded):
        ledger.record_observed_fill(oversized, writer_id="writer-A", writer_epoch=epoch)
    assert ledger.snapshot()["cash_actual_usdt"] == "100"
    assert ledger.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch)["filled_qty_btc"] == "0"
    ledger.close()


def test_decimal_precision_does_not_round_observed_fee_or_notional(tmp_path):
    path, ledger, epoch, iid = fixture(tmp_path)
    observation = {**fill(iid), "delta_qty_btc": "0.00000001", "cumulative_qty_btc": "0.00000001",
                   "price_usdt_per_btc": "1.23456789", "fee_usdt": "0.00000001"}
    with localcontext() as ctx:
        ctx.prec = 1
        ledger.record_observed_fill(observation, writer_id="writer-A", writer_epoch=epoch)
    state = ledger.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch)
    assert Decimal(state["spent_usdt"]) == Decimal("0.0000000223456789")
    assert Decimal(state["actual_cash_usdt"]) == Decimal("100") - Decimal("0.0000000223456789")
    assert Decimal(state["filled_qty_btc"]) + Decimal(state["remaining_qty_btc"]) == Decimal("0.1")
    ledger.close()


class _RollbackFaultConnection:
    """Keep the real SQLite/schema path but fail rollback itself."""
    def __init__(self, real):
        self._real = real
    def __getattr__(self, name):
        return getattr(self._real, name)
    def rollback(self):
        raise sqlite3.OperationalError("synthetic execution rollback failure")


def test_failed_rollback_after_partial_fill_write_halts_and_retains_both_failures(tmp_path, monkeypatch):
    path, ledger, epoch, iid = fixture(tmp_path)
    def fail(**kwargs):
        raise OSError("synthetic fill event write failure")
    monkeypatch.setattr(ledger, "_append_execution_event", fail)
    monkeypatch.setattr(ledger, "_conn", _RollbackFaultConnection(ledger._conn))
    with pytest.raises(PaperStorageError, match="rollback") as caught:
        ledger.record_observed_fill(fill(iid), writer_id="writer-A", writer_epoch=epoch)
    failures = caught.value.__cause__
    assert isinstance(failures, BaseExceptionGroup)
    assert isinstance(failures.exceptions[0], OSError)
    assert isinstance(failures.exceptions[1], sqlite3.OperationalError)
    with pytest.raises(Halted):
        ledger.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch)
    with pytest.raises(Halted):
        ledger.claim_writer("writer-B", expected_epoch=epoch)
    ledger.close()
    recovered = PaperLedger.open(path)
    assert recovered.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch)["filled_qty_btc"] == "0"
    assert recovered.snapshot()["cash_reserved_usdt"] == "21"
    recovered.close()


def test_fill_count_bound_does_not_drop_unresolved_record(tmp_path, monkeypatch):
    path, ledger, epoch, iid = fixture(tmp_path)
    first = fill(iid, delta="0.01", cumulative="0.01", fee="0.02")
    ledger.record_observed_fill(first, writer_id="writer-A", writer_epoch=epoch)
    monkeypatch.setattr("signal_desk.paper.ledger.MAX_FILLS_PER_INTENT", 1)
    with pytest.raises(PaperStorageError) as caught:
        ledger.record_observed_fill(fill(iid, fill_id="fill-2", delta="0.01", cumulative="0.02", fee="0.02", when=5),
            writer_id="writer-A", writer_epoch=epoch)
    assert "bound" in str(caught.value.__cause__)
    with pytest.raises(Halted):
        ledger.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch)
    ledger.close()
    monkeypatch.setattr("signal_desk.paper.ledger.MAX_FILLS_PER_INTENT", 16)
    reopened = PaperLedger.open(path)
    assert reopened.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch)["filled_qty_btc"] == "0.01"
    reopened.close()
