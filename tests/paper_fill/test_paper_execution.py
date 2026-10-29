"""Synthetic, explicitly observed local-paper execution accounting tests."""
from decimal import Decimal, localcontext
from datetime import datetime, timedelta, timezone

import pytest
import sqlite3
import json
import subprocess
import sys
import threading

from signal_desk.schemas.validate import SchemaValidationError, validate_json
from signal_desk.paper.ledger import (
    SCHEMAS, PaperLedger, IntentRequest, DuplicateConflict, StaleWriter, ClaimUnavailable,
    PaperStorageError, Halted, ReconciliationRequired,
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


def rewrite_synthetic_history(path, reorder):
    """Rehash a synthetic ledger after a deliberate cross-intent reordering."""
    from signal_desk.paper.ledger import REQUIRED_TRIGGERS, _digest, _json
    with sqlite3.connect(path) as raw:
        rows = [(seq, json.loads(payload)) for seq, payload in raw.execute(
            "SELECT seq,payload FROM ledger ORDER BY seq")]
        reordered = reorder([item for _, item in rows])
        assert len(reordered) == len(rows)
        raw.execute("DROP TRIGGER ledger_no_update")
        raw.execute("UPDATE ledger SET ledger_id=ledger_id||'_synthetic_swap'")
        previous = None
        for (seq, _), item in zip(rows, reordered):
            item["prev_hash"] = previous
            item["hash"] = _digest({key: value for key, value in item.items() if key != "hash"})
            raw.execute("UPDATE ledger SET ledger_id=?,payload=?,hash=?,prev_hash=? WHERE seq=?",
                        (item["ledger_id"], _json(item), item["hash"], previous, seq))
            previous = item["hash"]
        raw.execute("UPDATE meta SET last_hash=? WHERE id=1", (previous,))
        raw.execute(REQUIRED_TRIGGERS["ledger_no_update"])


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
    bad_cumulative = fill(iid, fill_id="synthetic-fill-2", delta="0.02", cumulative="0.04")
    incident = ledger.record_observed_fill(bad_cumulative, writer_id="writer-A", writer_epoch=epoch)
    assert incident["reason"] == "cumulative_mismatch"
    assert ledger.record_observed_fill(bad_cumulative, writer_id="writer-A", writer_epoch=epoch) == incident
    blocked_overfill = fill(iid, fill_id="synthetic-fill-3", delta="0.07", cumulative="0.11")
    assert ledger.record_observed_fill(blocked_overfill, writer_id="writer-A", writer_epoch=epoch)["reason"] == "unresolved_incident"
    assert ledger.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch) == before
    ledger.close()
    reopened = PaperLedger.open(path)
    assert reopened.record_observed_fill(first, writer_id="writer-A", writer_epoch=epoch) == result
    assert reopened.record_observed_fill(bad_cumulative, writer_id="writer-A", writer_epoch=epoch) == incident
    assert len(reopened.pending_incidents(writer_id="writer-A", writer_epoch=epoch)) == 2
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


@pytest.mark.parametrize("overrides, reason", [
    ({"price_usdt_per_btc": "2300"}, "accounting_limit"),
    ({"delta_qty_btc": "0.11", "cumulative_qty_btc": "0.11"}, "overfill"),
    ({"cumulative_qty_btc": "0.05"}, "cumulative_mismatch"),
])
def test_non_applicable_observed_fill_is_durable_incident_and_blocks_risk(tmp_path, overrides, reason):
    path, ledger, epoch, iid = fixture(tmp_path)
    observation = {**fill(iid), **overrides}
    before = ledger.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch)
    balances = ledger.snapshot()
    incident = ledger.record_observed_fill(observation, writer_id="writer-A", writer_epoch=epoch)
    assert incident == {"status": "RECONCILIATION_INCIDENT", "intent_id": iid,
                        "fill_id": observation["fill_id"], "reason": reason}
    assert ledger.record_observed_fill(observation, writer_id="writer-A", writer_epoch=epoch) == incident
    with pytest.raises(DuplicateConflict):
        ledger.record_observed_fill({**observation, "fee_usdt": "0.09"}, writer_id="writer-A", writer_epoch=epoch)
    assert ledger.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch) == before
    assert ledger.snapshot() == balances
    entries = ledger.ledger_entries(writer_id="writer-A", writer_epoch=epoch)
    assert entries[-1]["entry_type"] == "reconcile"
    assert entries[-1]["execution"]["reason"] == reason
    assert entries[-1]["execution"]["event"] == observation
    assert entries[-1]["execution"]["state_after"]["filled_qty_btc"] == "0"
    validate_json(entries[-1], "ledger_entry.schema.json", SCHEMAS)
    with pytest.raises(SchemaValidationError):
        validate_json({**entries[-1], "execution": {**entries[-1]["execution"], "reason": "not_allowed"}},
                      "ledger_entry.schema.json", SCHEMAS)
    with sqlite3.connect(path) as raw:
        assert raw.execute("SELECT count(*) FROM fills").fetchone()[0] == 0
        assert raw.execute("SELECT count(*) FROM incidents").fetchone()[0] == 1
    next_intent = IntentRequest(
        strategy_id="synthetic", signal_id="next-signal", feature_snapshot_id="synthetic-feature",
        decision_id="synthetic-decision", config_version="synthetic-config", plan_hash="synthetic-plan",
        portfolio_version=1, decision_time=at(10), valid_until=at(60), expires_at=at(120),
        qty_btc="0.1", price_ceiling_usdt_per_btc="200", fee_buffer_usdt="1", risk_reserve_usdt="2")
    with pytest.raises(ReconciliationRequired):
        ledger.reserve(next_intent, writer_id="writer-A", writer_epoch=epoch)
    ledger.close()
    reopened = PaperLedger.open(path)
    assert reopened.pending_incidents(writer_id="writer-A", writer_epoch=epoch) == [
        {"event": observation, "result": incident}]
    assert reopened.record_observed_fill(observation, writer_id="writer-A", writer_epoch=epoch) == incident
    with pytest.raises(DuplicateConflict):
        reopened.record_observed_fill({**observation, "fee_usdt": "0.09"}, writer_id="writer-A", writer_epoch=epoch)
    assert reopened.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch) == before
    assert reopened.snapshot() == balances
    with pytest.raises(ReconciliationRequired):
        reopened.reserve(next_intent, writer_id="writer-A", writer_epoch=epoch)
    reopened.close()


def test_recovery_rejects_reason_that_ignores_earlier_pre_acceptance_gate(tmp_path):
    path, ledger, epoch, iid = fixture(tmp_path)
    observation = fill(iid, delta="0.11", cumulative="0.11", when=1)
    assert ledger.record_observed_fill(observation, writer_id="writer-A", writer_epoch=epoch)["reason"] == "pre_acceptance"
    ledger.close()
    def change_reason(entries):
        assert entries[-1]["entry_type"] == "reconcile"
        entries[-1]["execution"]["reason"] = "overfill"
        return entries
    rewrite_synthetic_history(path, change_reason)
    from signal_desk.paper.ledger import REQUIRED_TRIGGERS, _json
    with sqlite3.connect(path) as raw:
        raw.execute("DROP TRIGGER incidents_no_update")
        row = json.loads(raw.execute("SELECT payload FROM incidents WHERE fill_id=?",
                                     (observation["fill_id"],)).fetchone()[0])
        row["result"]["reason"] = "overfill"
        raw.execute("UPDATE incidents SET payload=? WHERE fill_id=?",
                    (_json(row), observation["fill_id"]))
        raw.execute(REQUIRED_TRIGGERS["incidents_no_update"])
    with pytest.raises(PaperStorageError, match="incident|recovery"):
        PaperLedger.open(path)


def test_pre_acceptance_observation_is_retained_without_inventory_effect(tmp_path):
    path, ledger, epoch, iid = fixture(tmp_path)
    early = fill(iid, when=1)
    incident = ledger.record_observed_fill(early, writer_id="writer-A", writer_epoch=epoch)
    assert incident["reason"] == "pre_acceptance"
    assert ledger.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch)["filled_qty_btc"] == "0"
    assert ledger.snapshot()["cash_reserved_usdt"] == "21"
    ledger.close()
    reopened = PaperLedger.open(path)
    assert reopened.pending_incidents(writer_id="writer-A", writer_epoch=epoch) == [
        {"event": early, "result": incident}]
    reopened.close()


def test_incident_capacity_failure_halts_without_erasing_prior_evidence(tmp_path, monkeypatch):
    path, ledger, epoch, iid = fixture(tmp_path)
    monkeypatch.setattr("signal_desk.paper.ledger.MAX_INCIDENTS_PER_INTENT", 1)
    first = {**fill(iid), "price_usdt_per_btc": "2300"}
    incident = ledger.record_observed_fill(first, writer_id="writer-A", writer_epoch=epoch)
    with pytest.raises(PaperStorageError):
        ledger.record_observed_fill(fill(iid, fill_id="second-observation", when=5),
            writer_id="writer-A", writer_epoch=epoch)
    with pytest.raises(Halted):
        ledger.snapshot()
    ledger.close()
    reopened = PaperLedger.open(path)
    assert reopened.pending_incidents(writer_id="writer-A", writer_epoch=epoch) == [
        {"event": first, "result": incident}]
    assert reopened.snapshot()["cash_reserved_usdt"] == "21"
    reopened.close()


def test_accounting_incident_considers_other_intent_reservations(tmp_path):
    path, ledger, epoch, iid = fixture(tmp_path)
    second = IntentRequest(
        strategy_id="synthetic", signal_id="another-accepted-signal", feature_snapshot_id="synthetic-feature",
        decision_id="synthetic-decision", config_version="synthetic-config", plan_hash="synthetic-plan",
        portfolio_version=1, decision_time=at(3), valid_until=at(60), expires_at=at(120),
        qty_btc="0.1", price_ceiling_usdt_per_btc="200", fee_buffer_usdt="1", risk_reserve_usdt="2")
    other_id = ledger.reserve(second, writer_id="writer-A", writer_epoch=epoch)["intent_id"]
    envelope = ledger.claim_outbox(other_id, claim_id="claim-other", claim_version=1,
        claimed_at=at(4), writer_id="writer-A", writer_epoch=epoch)
    with LocalPaperReceiver(path) as receiver:
        receipt = receiver.accept(envelope, accepted_at=at(5))
    ledger.ack_receipt(other_id, receipt["receipt_id"], acked_at=at(6), writer_id="writer-A", writer_epoch=epoch)
    observation = {**fill(iid, when=7), "price_usdt_per_btc": "1700"}
    # This tentative fill would leave 31.92 cash but 33.6 reserved across
    # both intents; its own remainder alone would still fit.
    incident = ledger.record_observed_fill(observation, writer_id="writer-A", writer_epoch=epoch)
    assert incident["reason"] == "accounting_limit"
    assert ledger.snapshot()["cash_actual_usdt"] == "100"
    assert ledger.snapshot()["cash_reserved_usdt"] == "42"
    ledger.close()
    reopened = PaperLedger.open(path)
    assert reopened.pending_incidents(writer_id="writer-A", writer_epoch=epoch) == [
        {"event": observation, "result": incident}]
    reopened.close()


def test_recovery_rejects_applied_fill_after_reasoned_incident(tmp_path):
    path, ledger, epoch, iid = fixture(tmp_path)
    second = IntentRequest(
        strategy_id="synthetic", signal_id="other-risk", feature_snapshot_id="synthetic-feature",
        decision_id="synthetic-decision", config_version="synthetic-config", plan_hash="synthetic-plan",
        portfolio_version=1, decision_time=at(3), valid_until=at(60), expires_at=at(120),
        qty_btc="0.1", price_ceiling_usdt_per_btc="200", fee_buffer_usdt="1", risk_reserve_usdt="2")
    other_id = ledger.reserve(second, writer_id="writer-A", writer_epoch=epoch)["intent_id"]
    claim = ledger.claim_outbox(other_id, claim_id="other-claim", claim_version=1,
        claimed_at=at(4), writer_id="writer-A", writer_epoch=epoch)
    with LocalPaperReceiver(path) as receiver:
        receipt = receiver.accept(claim, accepted_at=at(5))
    ledger.ack_receipt(other_id, receipt["receipt_id"], acked_at=at(6), writer_id="writer-A", writer_epoch=epoch)
    ledger.record_observed_fill(fill(other_id, fill_id="other-fill", when=7),
        writer_id="writer-A", writer_epoch=epoch)
    assert ledger.record_observed_fill({**fill(iid, fill_id="bad-cost", when=8),
        "price_usdt_per_btc": "2300"}, writer_id="writer-A", writer_epoch=epoch)["reason"] == "accounting_limit"
    ledger.close()
    def swap_last_two(entries):
        assert [entry["entry_type"] for entry in entries[-2:]] == ["paper_fill", "reconcile"]
        entries[-2], entries[-1] = entries[-1], entries[-2]
        return entries
    rewrite_synthetic_history(path, swap_last_two)
    with pytest.raises(PaperStorageError, match="incident|recovery|chronology"):
        PaperLedger.open(path)


def test_recovery_preserves_historical_reasonless_terminal_incident_before_reservation(tmp_path):
    path, ledger, epoch, iid = fixture(tmp_path)
    second = IntentRequest(
        strategy_id="synthetic", signal_id="legacy-followup", feature_snapshot_id="synthetic-feature",
        decision_id="synthetic-decision", config_version="synthetic-config", plan_hash="synthetic-plan",
        portfolio_version=1, decision_time=at(3), valid_until=at(60), expires_at=at(120),
        qty_btc="0.1", price_ceiling_usdt_per_btc="200", fee_buffer_usdt="1", risk_reserve_usdt="2")
    other_id = ledger.reserve(second, writer_id="writer-A", writer_epoch=epoch)["intent_id"]
    ledger.record_observed_fill(fill(iid), writer_id="writer-A", writer_epoch=epoch)
    ledger.request_cancel(iid, cancel_id="legacy-cancel", requested_at=at(5),
        writer_id="writer-A", writer_epoch=epoch)
    ledger.confirm_cancel(iid, cancel_id="legacy-cancel", confirmed_at=at(6),
        writer_id="writer-A", writer_epoch=epoch)
    legacy = fill(iid, fill_id="legacy-terminal", delta="0.02", cumulative="0.06", when=7)
    terminal = ledger.record_observed_fill(legacy, writer_id="writer-A", writer_epoch=epoch)
    assert "reason" not in terminal
    ledger.close()
    def move_old_reservation_after_terminal(entries):
        second_entries = [item for item in entries if item["intent_id"] == other_id]
        assert [item["entry_type"] for item in second_entries] == ["intent_created", "risk_reserved"]
        return [item for item in entries if item["intent_id"] != other_id] + second_entries
    rewrite_synthetic_history(path, move_old_reservation_after_terminal)
    recovered = PaperLedger.open(path)
    assert recovered.pending_incidents(writer_id="writer-A", writer_epoch=epoch) == [
        {"event": legacy, "result": terminal}]
    assert recovered.execution_snapshot(other_id, writer_id="writer-A", writer_epoch=epoch)["status"] == "OPEN"
    recovered.close()


def test_recovery_rejects_new_reservation_after_reasoned_incident(tmp_path):
    path, ledger, epoch, iid = fixture(tmp_path)
    second = IntentRequest(
        strategy_id="synthetic", signal_id="later-risk", feature_snapshot_id="synthetic-feature",
        decision_id="synthetic-decision", config_version="synthetic-config", plan_hash="synthetic-plan",
        portfolio_version=1, decision_time=at(3), valid_until=at(60), expires_at=at(120),
        qty_btc="0.1", price_ceiling_usdt_per_btc="200", fee_buffer_usdt="1", risk_reserve_usdt="2")
    other_id = ledger.reserve(second, writer_id="writer-A", writer_epoch=epoch)["intent_id"]
    ledger.record_observed_fill({**fill(iid), "price_usdt_per_btc": "2300"},
        writer_id="writer-A", writer_epoch=epoch)
    ledger.close()
    def move_incident_before_second_intent(entries):
        start = next(n for n, entry in enumerate(entries) if entry["intent_id"] == other_id and
                     entry["entry_type"] == "intent_created")
        assert entries[-1]["entry_type"] == "reconcile"
        entries.insert(start, entries.pop())
        return entries
    rewrite_synthetic_history(path, move_incident_before_second_intent)
    with pytest.raises(PaperStorageError, match="incident"):
        PaperLedger.open(path)


def test_recovery_rejects_cancellation_release_after_reasoned_incident(tmp_path):
    path, ledger, epoch, iid = fixture(tmp_path)
    ledger.request_cancel(iid, cancel_id="pending-cancel", requested_at=at(5),
        writer_id="writer-A", writer_epoch=epoch)
    second = IntentRequest(
        strategy_id="synthetic", signal_id="second-accepted", feature_snapshot_id="synthetic-feature",
        decision_id="synthetic-decision", config_version="synthetic-config", plan_hash="synthetic-plan",
        portfolio_version=1, decision_time=at(3), valid_until=at(60), expires_at=at(120),
        qty_btc="0.1", price_ceiling_usdt_per_btc="200", fee_buffer_usdt="1", risk_reserve_usdt="2")
    other_id = ledger.reserve(second, writer_id="writer-A", writer_epoch=epoch)["intent_id"]
    claim = ledger.claim_outbox(other_id, claim_id="second-claim", claim_version=1,
        claimed_at=at(4), writer_id="writer-A", writer_epoch=epoch)
    with LocalPaperReceiver(path) as receiver:
        receipt = receiver.accept(claim, accepted_at=at(5))
    ledger.ack_receipt(other_id, receipt["receipt_id"], acked_at=at(6), writer_id="writer-A", writer_epoch=epoch)
    ledger.confirm_cancel(iid, cancel_id="pending-cancel", confirmed_at=at(7),
        writer_id="writer-A", writer_epoch=epoch)
    assert ledger.record_observed_fill({**fill(other_id, when=8), "price_usdt_per_btc": "2300"},
        writer_id="writer-A", writer_epoch=epoch)["reason"] == "accounting_limit"
    ledger.close()
    def swap_last_two(entries):
        assert [entry["entry_type"] for entry in entries[-2:]] == ["cancelled", "reconcile"]
        entries[-2], entries[-1] = entries[-1], entries[-2]
        return entries
    rewrite_synthetic_history(path, swap_last_two)
    with pytest.raises(PaperStorageError, match="incident"):
        PaperLedger.open(path)


def test_new_valid_observation_after_incident_is_retained_not_applied(tmp_path):
    path, ledger, epoch, iid = fixture(tmp_path)
    bad = {**fill(iid), "price_usdt_per_btc": "2300"}
    ledger.record_observed_fill(bad, writer_id="writer-A", writer_epoch=epoch)
    valid = fill(iid, fill_id="later-valid-fill", when=5)
    result = ledger.record_observed_fill(valid, writer_id="writer-A", writer_epoch=epoch)
    assert result["reason"] == "unresolved_incident"
    assert ledger.record_observed_fill(valid, writer_id="writer-A", writer_epoch=epoch) == result
    assert ledger.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch)["filled_qty_btc"] == "0"
    assert ledger.snapshot()["cash_actual_usdt"] == "100"
    ledger.close()
    reopened = PaperLedger.open(path)
    assert len(reopened.pending_incidents(writer_id="writer-A", writer_epoch=epoch)) == 2
    assert reopened.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch)["filled_qty_btc"] == "0"
    reopened.close()


def test_recovery_rejects_accounting_incident_if_fill_would_have_fit(tmp_path):
    path, ledger, epoch, iid = fixture(tmp_path)
    event = {**fill(iid), "price_usdt_per_btc": "2300"}
    assert ledger.record_observed_fill(event, writer_id="writer-A", writer_epoch=epoch)["reason"] == "accounting_limit"
    ledger.close()
    # Synthetic self-consistent incident payload/last event hash; the changed
    # price now fits, so recovery must independently verify the incident reason.
    from signal_desk.paper.ledger import REQUIRED_TRIGGERS, _digest, _json
    with sqlite3.connect(path) as raw:
        raw.execute("DROP TRIGGER ledger_no_update")
        raw.execute("DROP TRIGGER incidents_no_update")
        seq, text = raw.execute(
            "SELECT seq,payload FROM ledger ORDER BY seq DESC LIMIT 1").fetchone()
        entry = json.loads(text)
        assert entry["entry_type"] == "reconcile"
        entry["execution"]["event"]["price_usdt_per_btc"] = "200"
        entry["hash"] = _digest({key: value for key, value in entry.items() if key != "hash"})
        raw.execute("UPDATE ledger SET payload=?,hash=? WHERE seq=?", (_json(entry), entry["hash"], seq))
        raw.execute("UPDATE meta SET last_hash=? WHERE id=1", (entry["hash"],))
        payload = json.loads(raw.execute("SELECT payload FROM incidents WHERE fill_id=?", (event["fill_id"],)).fetchone()[0])
        payload["event"]["price_usdt_per_btc"] = "200"
        raw.execute("UPDATE incidents SET payload=? WHERE fill_id=?", (_json(payload), event["fill_id"]))
        raw.execute(REQUIRED_TRIGGERS["ledger_no_update"])
        raw.execute(REQUIRED_TRIGGERS["incidents_no_update"])
    with pytest.raises(PaperStorageError, match="incident|accounting|recovery"):
        PaperLedger.open(path)


def test_unresolved_cost_incident_prevents_cancel_remainder_release(tmp_path):
    path, ledger, epoch, iid = fixture(tmp_path)
    ledger.request_cancel(iid, cancel_id="pending-cancel", requested_at=at(5),
        writer_id="writer-A", writer_epoch=epoch)
    observation = {**fill(iid, when=6), "price_usdt_per_btc": "2300"}
    assert ledger.record_observed_fill(observation, writer_id="writer-A", writer_epoch=epoch)["reason"] == "accounting_limit"
    with pytest.raises(ReconciliationRequired):
        ledger.confirm_cancel(iid, cancel_id="pending-cancel", confirmed_at=at(7),
            writer_id="writer-A", writer_epoch=epoch)
    state = ledger.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch)
    assert state["status"] == "CANCEL_PENDING"
    assert state["cash_reserved_usdt"] == "21" and state["risk_reserved_usdt"] == "2"
    ledger.close()
    reopened = PaperLedger.open(path)
    with pytest.raises(ReconciliationRequired):
        reopened.confirm_cancel(iid, cancel_id="pending-cancel", confirmed_at=at(7),
            writer_id="writer-A", writer_epoch=epoch)
    assert reopened.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch) == state
    reopened.close()


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


def test_fill_count_bound_preserves_observation_as_incident(tmp_path, monkeypatch):
    path, ledger, epoch, iid = fixture(tmp_path)
    first = fill(iid, delta="0.01", cumulative="0.01", fee="0.02")
    ledger.record_observed_fill(first, writer_id="writer-A", writer_epoch=epoch)
    monkeypatch.setattr("signal_desk.paper.ledger.MAX_FILLS_PER_INTENT", 1)
    second = fill(iid, fill_id="fill-2", delta="0.01", cumulative="0.02", fee="0.02", when=5)
    incident = ledger.record_observed_fill(second, writer_id="writer-A", writer_epoch=epoch)
    assert incident["reason"] == "fill_limit"
    assert ledger.record_observed_fill(second, writer_id="writer-A", writer_epoch=epoch) == incident
    assert ledger.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch)["filled_qty_btc"] == "0.01"
    ledger.close()
    reopened = PaperLedger.open(path)
    assert reopened.pending_incidents(writer_id="writer-A", writer_epoch=epoch) == [
        {"event": second, "result": incident}]
    assert reopened.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch)["filled_qty_btc"] == "0.01"
    reopened.close()
