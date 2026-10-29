"""Synthetic local-paper delivery tests; no network sender, exchange or fill."""
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import os
import sqlite3
import subprocess
import sys

import pytest

from signal_desk.paper.ledger import (
    PaperLedger, IntentRequest, DuplicateConflict, StaleWriter, PaperStorageError,
    Halted, ClaimUnavailable, ReceiptPending,
)
from signal_desk.paper.local_receiver import LocalPaperReceiver


def at(seconds):
    return (datetime(2026, 10, 29, 12, tzinfo=timezone.utc) +
            timedelta(seconds=seconds)).isoformat(timespec="seconds").replace("+00:00", "Z")


def request():
    # Synthetic quantity, price, budgets and fee buffer: not real market or PnL.
    return IntentRequest(
        strategy_id="synthetic-strategy", signal_id="synthetic-signal",
        feature_snapshot_id="synthetic-feature", decision_id="synthetic-decision",
        config_version="synthetic-config", plan_hash="synthetic-plan",
        portfolio_version=0, decision_time=at(0), valid_until=at(300),
        expires_at=at(300), qty_btc="0.1", price_ceiling_usdt_per_btc="200",
        fee_buffer_usdt="1", risk_reserve_usdt="2")


def reserved(tmp_path):
    path = tmp_path / "paper.sqlite3"
    ledger = PaperLedger.create(path, cash_usdt="100", risk_budget_usdt="5")
    epoch = ledger.claim_writer("writer-A", expected_epoch=0)
    intent = ledger.reserve(request(), writer_id="writer-A", writer_epoch=epoch)
    return path, ledger, epoch, intent


def claim(ledger, epoch, *, version=1, claim_id="claim-1", when=0, writer="writer-A", intent_id=None):
    if intent_id is None:
        intent_id = ledger.pending_outbox(writer_id=writer, writer_epoch=epoch)[0]["intent_id"]
    return ledger.claim_outbox(intent_id, claim_id=claim_id, claim_version=version,
        claimed_at=at(when), writer_id=writer, writer_epoch=epoch)


def test_local_acceptance_ack_is_not_fill_and_keeps_reservation(tmp_path):
    path, ledger, epoch, intent = reserved(tmp_path)
    envelope = claim(ledger, epoch)
    assert envelope["payload"] == intent["outbox"]
    with LocalPaperReceiver(path) as receiver:
        receipt = receiver.accept(envelope, accepted_at=at(1))
        assert receipt["intent_id"] == intent["intent_id"]
        assert receipt["paper_only"] is True and receipt["kind"] == "ACCEPTED_NOT_FILLED"
    assert ledger.pending_outbox(writer_id="writer-A", writer_epoch=epoch) == []
    assert ledger.reconcile_receipt(intent["intent_id"], writer_id="writer-A", writer_epoch=epoch) == receipt
    ack = ledger.ack_receipt(intent["intent_id"], receipt["receipt_id"],
        acked_at=at(2), writer_id="writer-A", writer_epoch=epoch)
    assert ack["kind"] == "ACCEPTANCE_ACK_NOT_FILL"
    assert ledger.ack_receipt(intent["intent_id"], receipt["receipt_id"],
        acked_at=at(2), writer_id="writer-A", writer_epoch=epoch) == ack
    assert ledger.ack_receipt(intent["intent_id"], receipt["receipt_id"],
        acked_at=at(3), writer_id="writer-A", writer_epoch=epoch) == ack
    assert ledger.snapshot()["cash_reserved_usdt"] == "21"
    assert ledger.snapshot()["risk_reserved_usdt"] == "2"
    assert ledger.snapshot()["portfolio_version"] == 1
    ledger.close()


def test_competing_claims_and_same_claim_identity_conflicts(tmp_path):
    path, ledger, epoch, intent = reserved(tmp_path)
    first = claim(ledger, epoch)
    assert claim(ledger, epoch) == first
    with pytest.raises(DuplicateConflict):
        claim(ledger, epoch, claim_id="other-claim")
    with pytest.raises(ClaimUnavailable):
        claim(ledger, epoch, version=2, claim_id="claim-2", when=1)
    ledger.close()

    def attempt(claim_id):
        opened = PaperLedger.open(path)
        try:
            return opened.claim_outbox(intent["intent_id"], claim_id=claim_id,
                claim_version=2, claimed_at=at(30), writer_id="writer-A", writer_epoch=epoch)
        finally:
            opened.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(attempt, cid) for cid in ("claim-2a", "claim-2b")]
        successes = [f.result() for f in results if f.exception() is None]
        failures = [f.exception() for f in results if f.exception() is not None]
    assert len(successes) == 1 and len(failures) == 1
    assert isinstance(failures[0], DuplicateConflict)
    assert successes[0]["payload"]["intent_id"] == intent["intent_id"]


def test_receiver_rejects_stale_delivery_after_writer_takeover(tmp_path):
    path, first, epoch, intent = reserved(tmp_path)
    old = claim(first, epoch)
    new_writer = PaperLedger.open(path)
    new_epoch = new_writer.claim_writer("writer-B", expected_epoch=epoch)
    with LocalPaperReceiver(path) as receiver:
        with pytest.raises(StaleWriter):
            receiver.accept(old, accepted_at=at(1))
    with pytest.raises(StaleWriter):
        first.claim_outbox(intent["intent_id"], claim_id="old-retry", claim_version=2,
            claimed_at=at(1), writer_id="writer-A", writer_epoch=epoch)
    fresh = claim(new_writer, new_epoch, version=2, claim_id="claim-B", when=1,
                  writer="writer-B", intent_id=intent["intent_id"])
    with LocalPaperReceiver(path) as receiver:
        accepted = receiver.accept(fresh, accepted_at=at(2))
    assert accepted["intent_id"] == intent["intent_id"]
    first.close(); new_writer.close()


def test_duplicate_delivery_returns_one_receipt_but_conflicting_payload_fails(tmp_path):
    path, ledger, epoch, intent = reserved(tmp_path)
    envelope = claim(ledger, epoch)
    with LocalPaperReceiver(path) as receiver:
        first = receiver.accept(envelope, accepted_at=at(1))
        assert receiver.accept(envelope, accepted_at=at(1)) == first
        assert receiver.accept(envelope, accepted_at=at(3)) == first
        altered = {**envelope, "payload": {**envelope["payload"], "qty": "0.2"}}
        with pytest.raises(DuplicateConflict):
            receiver.accept(altered, accepted_at=at(1))
    assert ledger.reconcile_receipt(intent["intent_id"], writer_id="writer-A", writer_epoch=epoch) == first
    ledger.close()


def test_expired_claim_needs_receipt_check_before_bounded_retry(tmp_path):
    path, ledger, epoch, intent = reserved(tmp_path)
    first = claim(ledger, epoch)
    with LocalPaperReceiver(path) as receiver:
        with pytest.raises(ClaimUnavailable):
            receiver.accept(first, accepted_at=at(30))
    for version in range(2, 5):
        prior = claim(ledger, epoch, version=version, claim_id=f"claim-{version}", when=(version-1)*30)
        assert prior["payload"]["intent_id"] == intent["intent_id"]
    with pytest.raises(ClaimUnavailable):
        claim(ledger, epoch, version=5, claim_id="claim-5", when=120)
    assert ledger.snapshot()["risk_reserved_usdt"] == "2"
    ledger.close()


def test_crash_after_receipt_before_ack_reconciles_without_new_intent(tmp_path):
    path, ledger, epoch, intent = reserved(tmp_path)
    envelope = claim(ledger, epoch)
    with LocalPaperReceiver(path) as receiver:
        receipt = receiver.accept(envelope, accepted_at=at(1))
    ledger.close()
    reopened = PaperLedger.open(path)
    takeover = reopened.claim_writer("writer-B", expected_epoch=epoch)
    assert reopened.reconcile_receipt(intent["intent_id"], writer_id="writer-B", writer_epoch=takeover) == receipt
    assert reopened.reserve(request(), writer_id="writer-B", writer_epoch=takeover)["duplicate"] is True
    with pytest.raises(ReceiptPending):
        reopened.reserve(replace(request(), signal_id="synthetic-next", portfolio_version=1),
                         writer_id="writer-B", writer_epoch=takeover)
    with pytest.raises(ReceiptPending):
        reopened.claim_outbox(intent["intent_id"], claim_id="claim-new", claim_version=2,
            claimed_at=at(31), writer_id="writer-B", writer_epoch=takeover)
    assert reopened.pending_outbox(writer_id="writer-B", writer_epoch=takeover) == []
    ack = reopened.ack_receipt(intent["intent_id"], receipt["receipt_id"],
        acked_at=at(32), writer_id="writer-B", writer_epoch=takeover)
    assert ack["kind"] == "ACCEPTANCE_ACK_NOT_FILL"
    assert reopened.snapshot()["cash_reserved_usdt"] == "21"
    assert len(reopened.ledger_entries(writer_id="writer-B", writer_epoch=takeover)) == 5
    reopened.close()
    final = PaperLedger.open(path)
    final_epoch = final.claim_writer("writer-C", expected_epoch=takeover)
    assert final.reconcile_receipt(intent["intent_id"], writer_id="writer-C", writer_epoch=final_epoch) == receipt
    assert final.pending_outbox(writer_id="writer-C", writer_epoch=final_epoch) == []
    assert len(final.ledger_entries(writer_id="writer-C", writer_epoch=final_epoch)) == 5
    with pytest.raises(ClaimUnavailable):
        final.claim_outbox(intent["intent_id"], claim_id="claim-after-ack", claim_version=2,
            claimed_at=at(60), writer_id="writer-C", writer_epoch=final_epoch)
    assert final.snapshot()["portfolio_version"] == 1
    final.close()


def test_crash_before_receipt_commit_has_no_local_effect(tmp_path):
    path, ledger, epoch, intent = reserved(tmp_path)
    envelope = claim(ledger, epoch)
    ledger.close()
    child = """import json,os,sys
from signal_desk.paper.ledger import PaperLedger
store=PaperLedger.open(sys.argv[1])
original=store._append_dispatch_event
def crash(*args,**kwargs):
    os._exit(37)
store._append_dispatch_event=crash
store.accept_local(json.loads(sys.argv[2]),accepted_at=sys.argv[3])
"""
    result = subprocess.run([sys.executable, "-c", child, str(path), json.dumps(envelope), at(1)], capture_output=True)
    assert result.returncode == 37, result.stderr
    recovered = PaperLedger.open(path)
    takeover = recovered.claim_writer("writer-B", expected_epoch=epoch)
    assert recovered.reconcile_receipt(intent["intent_id"], writer_id="writer-B", writer_epoch=takeover) is None
    assert recovered.snapshot()["risk_reserved_usdt"] == "2"
    recovered.close()


def test_explicit_v1_migration_preserves_intent_reservations_and_outbox(tmp_path):
    path, original, epoch, intent = reserved(tmp_path)
    original.close()
    from signal_desk.paper.ledger import LEGACY_TRIGGERS, REQUIRED_TRIGGERS
    with sqlite3.connect(path) as raw:
        for name in REQUIRED_TRIGGERS.keys() - LEGACY_TRIGGERS.keys():
            raw.execute(f"DROP TRIGGER {name}")  # fixed in-repository names
        for table in ("acks", "receipts", "claims"):
            raw.execute(f"DROP TABLE {table}")  # fixed in-repository names
        raw.execute("UPDATE meta SET schema_version=1 WHERE id=1")
    with pytest.raises(PaperStorageError, match="migrate_v1"):
        PaperLedger.open(path)
    migrated = PaperLedger.migrate_v1(path)
    assert migrated.snapshot()["cash_reserved_usdt"] == "21"
    assert migrated.snapshot()["portfolio_version"] == 1
    assert migrated.pending_outbox(writer_id="writer-A", writer_epoch=epoch) == [intent["outbox"]]
    envelope = claim(migrated, epoch)
    with LocalPaperReceiver(path) as receiver:
        receipt = receiver.accept(envelope, accepted_at=at(1))
    assert migrated.reconcile_receipt(intent["intent_id"], writer_id="writer-A", writer_epoch=epoch) == receipt
    migrated.close()
    with pytest.raises(PaperStorageError, match="Only verified schema v1"):
        PaperLedger.migrate_v1(path)


def test_restart_rejects_tampered_claim_or_receipt(tmp_path):
    path, ledger, epoch, intent = reserved(tmp_path)
    envelope = claim(ledger, epoch)
    with LocalPaperReceiver(path) as receiver:
        receiver.accept(envelope, accepted_at=at(1))
    ledger.close()
    from signal_desk.paper.ledger import REQUIRED_TRIGGERS
    with sqlite3.connect(path) as raw:
        raw.execute("DROP TRIGGER receipts_no_update")
        raw.execute("UPDATE receipts SET receipt=? WHERE intent_id=?",
                    (json.dumps({"kind": "FILLED"}), intent["intent_id"]))
        raw.execute(REQUIRED_TRIGGERS["receipts_no_update"])
    with pytest.raises(PaperStorageError, match="Local acceptance differs"):
        PaperLedger.open(path)


def test_claim_write_failure_halts_without_publishing_claim(tmp_path, monkeypatch):
    path, ledger, epoch, intent = reserved(tmp_path)
    def fail(*args, **kwargs):
        raise OSError("synthetic claim ledger failure")
    monkeypatch.setattr(ledger, "_append_dispatch_event", fail)
    with pytest.raises(PaperStorageError):
        claim(ledger, epoch)
    with pytest.raises(Halted):
        ledger.pending_outbox(writer_id="writer-A", writer_epoch=epoch)
    ledger.close()
    reopened = PaperLedger.open(path)
    assert reopened.snapshot()["risk_reserved_usdt"] == "2"
    assert reopened.claim_outbox(intent["intent_id"], claim_id="claim-1", claim_version=1,
        claimed_at=at(0), writer_id="writer-A", writer_epoch=epoch)["claim_version"] == 1
    reopened.close()


def test_ack_write_failure_preserves_receipt_for_reconciliation(tmp_path, monkeypatch):
    path, ledger, epoch, intent = reserved(tmp_path)
    envelope = claim(ledger, epoch)
    with LocalPaperReceiver(path) as receiver:
        receipt = receiver.accept(envelope, accepted_at=at(1))
    def fail(*args, **kwargs):
        raise OSError("synthetic ACK ledger failure")
    monkeypatch.setattr(ledger, "_append_dispatch_event", fail)
    with pytest.raises(PaperStorageError):
        ledger.ack_receipt(intent["intent_id"], receipt["receipt_id"],
            acked_at=at(2), writer_id="writer-A", writer_epoch=epoch)
    with pytest.raises(Halted):
        ledger.claim_writer("writer-B", expected_epoch=epoch)
    ledger.close()
    reopened = PaperLedger.open(path)
    new_epoch = reopened.claim_writer("writer-B", expected_epoch=epoch)
    assert reopened.reconcile_receipt(intent["intent_id"], writer_id="writer-B", writer_epoch=new_epoch) == receipt
    assert reopened.ack_receipt(intent["intent_id"], receipt["receipt_id"],
        acked_at=at(2), writer_id="writer-B", writer_epoch=new_epoch)["kind"] == "ACCEPTANCE_ACK_NOT_FILL"
    reopened.close()


def test_acceptance_write_failure_halts_and_leaves_no_receipt(tmp_path, monkeypatch):
    path, ledger, epoch, intent = reserved(tmp_path)
    envelope = claim(ledger, epoch)
    def fail(*args, **kwargs):
        raise OSError("synthetic local receipt write failure")
    monkeypatch.setattr(ledger, "_append_dispatch_event", fail)
    with pytest.raises(PaperStorageError):
        ledger.accept_local(envelope, accepted_at=at(1))
    with pytest.raises(Halted):
        ledger.claim_outbox(intent["intent_id"], claim_id="claim-2", claim_version=2,
            claimed_at=at(30), writer_id="writer-A", writer_epoch=epoch)
    ledger.close()
    restored = PaperLedger.open(path)
    owner = restored.claim_writer("writer-B", expected_epoch=epoch)
    assert restored.reconcile_receipt(intent["intent_id"], writer_id="writer-B", writer_epoch=owner) is None
    restored.close()
