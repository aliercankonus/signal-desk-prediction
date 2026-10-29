"""Bounded, synthetic-only private journal and explicit incident resolution."""
import hashlib
import json
import sqlite3
import subprocess
import sys

import pytest

from signal_desk.paper.ledger import (PaperLedger, IntentRequest, ReconciliationRequired, DuplicateConflict,
    StaleWriter, PaperStorageError, Halted)
from test_paper_execution import fixture, fill, at
from test_paper_execution import rewrite_synthetic_history


def execution(iid, fid, *, evidence_id="ev-1", source_execution_id="exec-1", price="2300", when=4, aliases=None):
    return {"evidence_id": evidence_id, "intent_id": iid, "source_kind": "synthetic_private_paper_journal",
            "source_identity": "synthetic-private", "source_sequence": 1, "kind": "EXECUTION",
            "source_execution_id": source_execution_id, "execution_ts": at(when),
            "delta_qty_btc": "0.04", "price_usdt_per_btc": price, "fee_usdt": "0.08",
            "observed_fill_ids": aliases or [fid]}


def seal(iid, ids=(), *, evidence_id="seal-1", when=5):
    return {"evidence_id": evidence_id, "intent_id": iid, "source_kind": "synthetic_private_paper_journal",
            "source_identity": "synthetic-private", "source_sequence": 2 if ids else 1, "kind": "FINAL_COMPLETE",
            "coverage_until": at(when), "execution_evidence_ids": list(ids)}


def register(ledger, record, epoch=1):
    return ledger.register_execution_evidence(record, writer_id="writer-A", writer_epoch=epoch)


def incident(ledger, iid, *, price="2300", fid="synthetic-fill-1", when=4, delta="0.04", cumulative="0.04", fee="0.08"):
    obs = {**fill(iid, fill_id=fid, delta=delta, cumulative=cumulative, fee=fee, when=when),
           "price_usdt_per_btc": price}
    result = ledger.record_observed_fill(obs, writer_id="writer-A", writer_epoch=1)
    assert result["status"] == "RECONCILIATION_INCIDENT"
    entry = ledger.ledger_entries(writer_id="writer-A", writer_epoch=1)[-1]
    return obs, result, entry["hash"]


def resolve(ledger, fid, incident_hash, ref, *, decision="VERIFIED_EXECUTION", rid="resolution-1", head=None):
    request = {"reconciliation_id": rid, "fill_id": fid, "incident_hash": incident_hash,
               "evidence_id": ref["evidence_id"], "evidence_sha256": ref["sha256"],
               "expected_head_hash": head or ledger.ledger_entries(writer_id="writer-A", writer_epoch=1)[-1]["hash"],
               "decision": decision}
    return request, ledger.reconcile_incident(request, writer_id="writer-A", writer_epoch=1)


def test_verified_execution_records_actual_deficit_atomically_and_replays(tmp_path):
    path, ledger, epoch, iid = fixture(tmp_path)
    ref = register(ledger, execution(iid, "synthetic-fill-1"))
    obs, _, original = incident(ledger, iid)
    request, result = resolve(ledger, obs["fill_id"], original, ref)
    assert result["status"] == "VERIFIED_EXECUTION"
    resolution_entry = ledger.ledger_entries(writer_id="writer-A", writer_epoch=epoch)[-1]
    assert resolution_entry["amounts"] == {"cash_delta_usdt": "-92.08", "base_delta_btc": "0.04",
                                           "cash_reserve_delta_usdt": "-8.4", "risk_reserve_delta_usdt": "-0.8",
                                           "risk_exposure_delta_usdt": "0.8"}
    assert ledger.reconcile_incident(request, writer_id="writer-A", writer_epoch=epoch) == result
    assert ledger.pending_incidents(writer_id="writer-A", writer_epoch=epoch) == []
    state = ledger.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch)
    assert state["filled_qty_btc"] == "0.04" and state["cash_reserved_usdt"] == "12.6"
    assert state["actual_cash_usdt"] == "7.92" and state["available_cash_usdt"] == "-4.68"
    assert ledger.snapshot()["cash_deficit_usdt"] == "4.68"
    ledger.close()
    reopened = PaperLedger.open(path)
    assert reopened.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch) == state
    assert reopened.reconcile_incident(request, writer_id="writer-A", writer_epoch=epoch) == result
    reopened.close()


def test_seal_proves_negative_only_with_complete_precommitted_set(tmp_path):
    path, ledger, epoch, iid = fixture(tmp_path)
    ref = register(ledger, seal(iid))
    obs, _, original = incident(ledger, iid, price="2300")
    _, result = resolve(ledger, obs["fill_id"], original, ref, decision="VERIFIED_NONEXECUTION")
    assert result["status"] == "VERIFIED_NONEXECUTION"
    assert ledger.snapshot()["cash_actual_usdt"] == "100"
    next_request = IntentRequest(
        strategy_id="synthetic", signal_id="after-closure", feature_snapshot_id="synthetic-feature",
        decision_id="synthetic-decision", config_version="synthetic-config", plan_hash="synthetic-plan",
        portfolio_version=1, decision_time=at(10), valid_until=at(60), expires_at=at(120),
        qty_btc="0.1", price_ceiling_usdt_per_btc="200", fee_buffer_usdt="1", risk_reserve_usdt="2")
    with pytest.raises(ReconciliationRequired):
        ledger.reserve(next_request, writer_id="writer-A", writer_epoch=epoch)
    ledger.close()
    PaperLedger.open(path).close()


def test_second_nonexecution_resolution_reopens_after_prior_verified_deficit(tmp_path):
    path, ledger, epoch, iid = fixture(tmp_path)
    execution_ref = register(ledger, execution(iid, "synthetic-fill-1"))
    seal_ref = register(ledger, seal(iid, ["ev-1"]))
    first, _, first_hash = incident(ledger, iid)
    second, _, second_hash = incident(ledger, iid, fid="second-incident", price="200", when=5)
    resolve(ledger, first["fill_id"], first_hash, execution_ref, rid="first-resolution")
    assert ledger.snapshot()["cash_deficit_usdt"] == "4.68"
    resolve(ledger, second["fill_id"], second_hash, seal_ref,
            decision="VERIFIED_NONEXECUTION", rid="second-resolution")
    assert ledger.pending_incidents(writer_id="writer-A", writer_epoch=epoch) == []
    ledger.close()
    reopened = PaperLedger.open(path)
    assert reopened.snapshot()["cash_deficit_usdt"] == "4.68"
    assert reopened.pending_incidents(writer_id="writer-A", writer_epoch=epoch) == []
    reopened.close()


def test_negative_seal_cannot_contradict_prior_applied_fill(tmp_path):
    path, ledger, epoch, iid = fixture(tmp_path)
    ref = register(ledger, seal(iid, when=6))
    applied = fill(iid)
    ledger.record_observed_fill(applied, writer_id="writer-A", writer_epoch=epoch)
    obs, _, original = incident(ledger, iid, fid="contradictory", price="200",
                                when=5, delta="0.02", cumulative="0.04")
    with pytest.raises(ReconciliationRequired, match="coverage|applied|journal"):
        resolve(ledger, obs["fill_id"], original, ref, decision="VERIFIED_NONEXECUTION")
    assert ledger.pending_incidents(writer_id="writer-A", writer_epoch=epoch)
    assert ledger.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch)["filled_qty_btc"] == "0.04"
    ledger.close()


def test_negative_seal_rejects_two_applied_aliases_for_one_execution(tmp_path):
    path, ledger, epoch, iid = fixture(tmp_path)
    journal = {**execution(iid, "ordinary-a", price="200", aliases=["ordinary-a", "ordinary-b"]),
               "delta_qty_btc": "0.02", "fee_usdt": "0"}
    register(ledger, journal)
    ref = register(ledger, seal(iid, ["ev-1"], when=6))
    for fid, cumulative in (("ordinary-a", "0.02"), ("ordinary-b", "0.04")):
        ledger.record_observed_fill(fill(iid, fill_id=fid, delta="0.02", cumulative=cumulative,
                                         fee="0"), writer_id="writer-A", writer_epoch=epoch)
    obs, _, original = incident(ledger, iid, fid="unrelated-incident", price="200",
                                when=5, delta="0.01", cumulative="0.04")
    with pytest.raises(ReconciliationRequired, match="journal|source|duplicate|coverage"):
        resolve(ledger, obs["fill_id"], original, ref, decision="VERIFIED_NONEXECUTION")
    assert ledger.snapshot()["base_actual_btc"] == "0.04"
    assert len(ledger.pending_incidents(writer_id="writer-A", writer_epoch=epoch)) == 1
    ledger.close()


def test_complete_negative_seal_matches_distinct_applied_source_executions(tmp_path):
    path, ledger, epoch, iid = fixture(tmp_path)
    for n, fid in enumerate(("ordinary-a", "ordinary-b"), 1):
        record = {**execution(iid, fid, evidence_id=f"source-{n}",
                              source_execution_id=f"execution-{n}", price="200"),
                  "source_sequence": n, "delta_qty_btc": "0.02", "fee_usdt": "0"}
        register(ledger, record)
    seal_record = {**seal(iid, ["source-1", "source-2"], when=6), "source_sequence": 3}
    ref = register(ledger, seal_record)
    for fid, cumulative in (("ordinary-a", "0.02"), ("ordinary-b", "0.04")):
        ledger.record_observed_fill(fill(iid, fill_id=fid, delta="0.02", cumulative=cumulative,
                                         fee="0"), writer_id="writer-A", writer_epoch=epoch)
    obs, _, original = incident(ledger, iid, fid="unrelated-incident", price="200",
                                when=5, delta="0.01", cumulative="0.04")
    assert resolve(ledger, obs["fill_id"], original, ref,
                   decision="VERIFIED_NONEXECUTION")[1]["status"] == "VERIFIED_NONEXECUTION"
    assert ledger.snapshot()["base_actual_btc"] == "0.04"
    ledger.close()
    PaperLedger.open(path).close()


def test_complete_negative_seal_accepts_prior_applied_fill_with_source_match(tmp_path):
    path, ledger, epoch, iid = fixture(tmp_path)
    register(ledger, execution(iid, "synthetic-fill-1", price="200"))
    seal_ref = register(ledger, seal(iid, ["ev-1"], when=6))
    ledger.record_observed_fill(fill(iid), writer_id="writer-A", writer_epoch=epoch)
    obs, _, original = incident(ledger, iid, fid="contradictory", price="200",
                                when=5, delta="0.02", cumulative="0.04")
    resolve(ledger, obs["fill_id"], original, seal_ref, decision="VERIFIED_NONEXECUTION")
    assert ledger.snapshot()["base_actual_btc"] == "0.04"
    ledger.close()
    PaperLedger.open(path).close()


def test_verified_corrections_share_applied_fill_capacity_across_restart(tmp_path):
    from decimal import Decimal
    path, ledger, epoch, iid = fixture(tmp_path)
    one = {**execution(iid, "cap-incident-1", evidence_id="cap-evidence-1",
                       source_execution_id="cap-source-1", price="100000"),
           "delta_qty_btc": "0.001", "fee_usdt": "0"}
    two = {**execution(iid, "cap-incident-2", evidence_id="cap-evidence-2",
                       source_execution_id="cap-source-2", price="200", when=5),
           "source_sequence": 2, "delta_qty_btc": "0.001", "fee_usdt": "0"}
    first_ref = register(ledger, one)
    second_ref = register(ledger, two)
    for n in range(1, 16):
        event = fill(iid, fill_id=f"ordinary-{n}", delta="0.001",
                     cumulative=str(Decimal(n) / Decimal(1000)), fee="0")
        ledger.record_observed_fill(event, writer_id="writer-A", writer_epoch=epoch)
    first, _, first_hash = incident(ledger, iid, fid="cap-incident-1", price="100000",
                                    delta="0.001", cumulative="0.016", fee="0")
    second, _, second_hash = incident(ledger, iid, fid="cap-incident-2", price="200",
                                      when=5, delta="0.001", cumulative="0.017", fee="0")
    assert first_ref["evidence_id"] == "cap-evidence-1"
    resolve(ledger, first["fill_id"], first_hash, first_ref, rid="first-cap-resolution")
    before = ledger.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch)
    assert before["filled_qty_btc"] == "0.016"
    with pytest.raises(ReconciliationRequired, match="fill|bound|capacity|Unsupported"):
        resolve(ledger, second["fill_id"], second_hash, second_ref, rid="second-cap-resolution")
    assert ledger.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch) == before
    assert [row["event"]["fill_id"] for row in ledger.pending_incidents(
        writer_id="writer-A", writer_epoch=epoch)] == ["cap-incident-2"]
    ledger.close()
    reopened = PaperLedger.open(path)
    assert reopened.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch) == before
    reopened.close()


@pytest.mark.parametrize("with_execution", [False, True])
def test_final_seal_rejects_missing_source_sequence_prefix_or_gap(tmp_path, with_execution):
    path, ledger, epoch, iid = fixture(tmp_path)
    if with_execution:
        register(ledger, execution(iid, "known-execution"))
        record = {**seal(iid, ["ev-1"]), "source_sequence": 3}
    else:
        record = {**seal(iid), "source_sequence": 2}
    with pytest.raises(ReconciliationRequired, match="sequence|complete|source"):
        register(ledger, record)
    ledger.close()


def test_recovery_rejects_rehashed_missing_journal_sequence(tmp_path):
    from signal_desk.paper.ledger import REQUIRED_TRIGGERS, _json
    path, ledger, epoch, iid = fixture(tmp_path)
    register(ledger, execution(iid, "known-execution"))
    final = seal(iid, ["ev-1"])
    register(ledger, final)
    ledger.close()
    altered = {**final, "source_sequence": 3}
    text = _json(altered)
    digest = hashlib.sha256(text.encode("ascii")).hexdigest()
    def mutate(entries):
        item = entries[-1]
        assert item["entry_type"] == "evidence_registered"
        item["evidence"] = altered
        item["evidence_sha256"] = digest
        item["evidence_byte_length"] = len(text.encode("ascii"))
        return entries
    rewrite_synthetic_history(path, mutate)
    with sqlite3.connect(path) as raw:
        raw.execute("DROP TRIGGER evidence_no_update")
        raw.execute("UPDATE evidence SET payload=?,byte_length=?,sha256=? WHERE evidence_id=?",
                    (text, len(text.encode("ascii")), digest, final["evidence_id"]))
        raw.execute(REQUIRED_TRIGGERS["evidence_no_update"])
    with pytest.raises(PaperStorageError, match="sequence|journal"):
        PaperLedger.open(path)


def test_seal_rejects_incomplete_set_and_later_registration(tmp_path):
    path, ledger, epoch, iid = fixture(tmp_path)
    register(ledger, execution(iid, "other-fill"))
    with pytest.raises(ReconciliationRequired):
        register(ledger, seal(iid))
    ref = register(ledger, seal(iid, ["ev-1"]))
    with pytest.raises(ReconciliationRequired):
        register(ledger, execution(iid, "other-fill", evidence_id="ev-2"))
    ledger.close()
    PaperLedger.open(path).close()


def test_missing_contradictory_and_late_evidence_leave_incident_open(tmp_path):
    path, ledger, epoch, iid = fixture(tmp_path)
    wrong = register(ledger, execution(iid, "different-fill"))
    obs, _, original = incident(ledger, iid)
    with pytest.raises(ReconciliationRequired):
        resolve(ledger, obs["fill_id"], original, wrong)
    late = {**execution(iid, obs["fill_id"], evidence_id="ev-late", source_execution_id="exec-late"),
            "source_sequence": 2}
    ref = register(ledger, late)
    with pytest.raises(ReconciliationRequired):
        resolve(ledger, obs["fill_id"], original, ref)
    assert len(ledger.pending_incidents(writer_id="writer-A", writer_epoch=epoch)) == 1
    ledger.close()


def test_resolution_revision_idempotence_conflict_and_writer_fence(tmp_path):
    path, ledger, epoch, iid = fixture(tmp_path)
    ref = register(ledger, seal(iid))
    obs, _, original = incident(ledger, iid)
    stale = ledger.ledger_entries(writer_id="writer-A", writer_epoch=epoch)[-2]["hash"]
    with pytest.raises(ReconciliationRequired):
        resolve(ledger, obs["fill_id"], original, ref, decision="VERIFIED_NONEXECUTION", head=stale)
    req, result = resolve(ledger, obs["fill_id"], original, ref, decision="VERIFIED_NONEXECUTION")
    assert ledger.reconcile_incident(req, writer_id="writer-A", writer_epoch=epoch) == result
    with pytest.raises(DuplicateConflict):
        ledger.reconcile_incident({**req, "decision": "VERIFIED_EXECUTION"}, writer_id="writer-A", writer_epoch=epoch)
    other = PaperLedger.open(path)
    other.claim_writer("writer-B", expected_epoch=epoch)
    with pytest.raises(StaleWriter):
        ledger.reconcile_incident(req, writer_id="writer-A", writer_epoch=epoch)
    other.close(); ledger.close()


def test_duplicate_proof_rejects_conflicting_source_alias_at_registration(tmp_path):
    path, ledger, epoch, iid = fixture(tmp_path)
    register(ledger, execution(iid, "dup-incident", price="200",
                               aliases=["ordinary-fill", "dup-incident"]))
    rival = {**execution(iid, "ordinary-fill", evidence_id="rival-evidence",
                         source_execution_id="rival-execution", price="200",
                         aliases=["ordinary-fill"]), "source_sequence": 2}
    with pytest.raises(DuplicateConflict, match="alias|source|execution"):
        register(ledger, rival)
    assert ledger.snapshot()["cash_actual_usdt"] == "100"
    ledger.close()
    PaperLedger.open(path).close()


def test_recovery_rejects_rehashed_conflicting_source_alias(tmp_path):
    from signal_desk.paper.ledger import REQUIRED_TRIGGERS, _json
    path, ledger, epoch, iid = fixture(tmp_path)
    register(ledger, execution(iid, "ordinary-fill"))
    rival = {**execution(iid, "unrelated-fill", evidence_id="rival-evidence",
                         source_execution_id="rival-execution"), "source_sequence": 2}
    register(ledger, rival)
    ledger.close()
    altered = {**rival, "observed_fill_ids": ["ordinary-fill"]}
    text = _json(altered)
    digest = hashlib.sha256(text.encode("ascii")).hexdigest()
    def mutate(entries):
        item = entries[-1]
        assert item["entry_type"] == "evidence_registered"
        item["evidence"] = altered
        item["evidence_sha256"] = digest
        item["evidence_byte_length"] = len(text.encode("ascii"))
        return entries
    rewrite_synthetic_history(path, mutate)
    with sqlite3.connect(path) as raw:
        raw.execute("DROP TRIGGER evidence_no_update")
        raw.execute("UPDATE evidence SET payload=?,byte_length=?,sha256=? WHERE evidence_id=?",
                    (text, len(text.encode("ascii")), digest, "rival-evidence"))
        raw.execute(REQUIRED_TRIGGERS["evidence_no_update"])
    with pytest.raises(PaperStorageError, match="journal|conflicting|alias"):
        PaperLedger.open(path)


def test_source_execution_identity_cannot_be_reused_for_another_intent(tmp_path):
    path, ledger, epoch, iid = fixture(tmp_path)
    register(ledger, execution(iid, "first-incident"))
    second = IntentRequest(
        strategy_id="synthetic", signal_id="second-intent", feature_snapshot_id="synthetic-feature",
        decision_id="synthetic-decision", config_version="synthetic-config", plan_hash="synthetic-plan",
        portfolio_version=1, decision_time=at(4), valid_until=at(60), expires_at=at(120),
        qty_btc="0.1", price_ceiling_usdt_per_btc="200", fee_buffer_usdt="1", risk_reserve_usdt="2")
    other_id = ledger.reserve(second, writer_id="writer-A", writer_epoch=epoch)["intent_id"]
    cross = {**execution(other_id, "other-incident", evidence_id="other-evidence"),
             "source_sequence": 1}
    with pytest.raises(DuplicateConflict, match="source|execution"):
        register(ledger, cross)
    ledger.close()
    PaperLedger.open(path).close()


def test_recovery_rejects_rehashed_cross_intent_source_identity_reuse(tmp_path):
    from signal_desk.paper.ledger import REQUIRED_TRIGGERS, _json
    path, ledger, epoch, iid = fixture(tmp_path)
    register(ledger, execution(iid, "first-incident"))
    second = IntentRequest(
        strategy_id="synthetic", signal_id="second-intent", feature_snapshot_id="synthetic-feature",
        decision_id="synthetic-decision", config_version="synthetic-config", plan_hash="synthetic-plan",
        portfolio_version=1, decision_time=at(4), valid_until=at(60), expires_at=at(120),
        qty_btc="0.1", price_ceiling_usdt_per_btc="200", fee_buffer_usdt="1", risk_reserve_usdt="2")
    other_id = ledger.reserve(second, writer_id="writer-A", writer_epoch=epoch)["intent_id"]
    original = {**execution(other_id, "other-incident", evidence_id="other-evidence",
                            source_execution_id="independent-execution"), "source_sequence": 1}
    register(ledger, original)
    ledger.close()
    altered = {**original, "source_execution_id": "exec-1"}
    text = _json(altered)
    digest = hashlib.sha256(text.encode("ascii")).hexdigest()
    def mutate(entries):
        item = entries[-1]
        assert item["entry_type"] == "evidence_registered"
        item["evidence"] = altered
        item["evidence_sha256"] = digest
        item["evidence_byte_length"] = len(text.encode("ascii"))
        return entries
    rewrite_synthetic_history(path, mutate)
    with sqlite3.connect(path) as raw:
        raw.execute("DROP TRIGGER evidence_no_update")
        raw.execute("UPDATE evidence SET payload=?,byte_length=?,sha256=? WHERE evidence_id=?",
                    (text, len(text.encode("ascii")), digest, "other-evidence"))
        raw.execute(REQUIRED_TRIGGERS["evidence_no_update"])
    with pytest.raises(PaperStorageError, match="source execution|identity"):
        PaperLedger.open(path)


def test_verified_duplicate_needs_precommitted_shared_source_execution(tmp_path):
    path, ledger, epoch, iid = fixture(tmp_path)
    ref = register(ledger, execution(iid, "late-duplicate", price="200", aliases=["synthetic-fill-1", "late-duplicate"]))
    ledger.record_observed_fill(fill(iid), writer_id="writer-A", writer_epoch=epoch)
    ledger.request_cancel(iid, cancel_id="stop", requested_at=at(5), writer_id="writer-A", writer_epoch=epoch)
    ledger.confirm_cancel(iid, cancel_id="stop", confirmed_at=at(6), writer_id="writer-A", writer_epoch=epoch)
    obs, _, original = incident(ledger, iid, fid="late-duplicate", price="200", delta="0.04", cumulative="0.04")
    _, result = resolve(ledger, obs["fill_id"], original, ref, decision="VERIFIED_DUPLICATE")
    assert result["status"] == "VERIFIED_DUPLICATE"
    assert ledger.snapshot()["cash_actual_usdt"] == "91.92"
    ledger.close(); PaperLedger.open(path).close()


def test_resolution_write_failure_rolls_back_and_reopens(tmp_path, monkeypatch):
    path, ledger, epoch, iid = fixture(tmp_path)
    ref = register(ledger, seal(iid))
    obs, _, original = incident(ledger, iid)
    def fail(*args, **kwargs):
        raise OSError("synthetic write failure")
    monkeypatch.setattr(ledger, "_append_incident_resolution", fail)
    with pytest.raises(PaperStorageError):
        resolve(ledger, obs["fill_id"], original, ref, decision="VERIFIED_NONEXECUTION")
    with pytest.raises(Halted):
        ledger.snapshot()
    ledger.close()
    recovered = PaperLedger.open(path)
    assert len(recovered.pending_incidents(writer_id="writer-A", writer_epoch=epoch)) == 1
    recovered.close()


def test_crash_before_resolution_commit_preserves_incident_and_evidence(tmp_path):
    path, ledger, epoch, iid = fixture(tmp_path)
    ref = register(ledger, execution(iid, "synthetic-fill-1"))
    obs, _, original = incident(ledger, iid)
    head = ledger.ledger_entries(writer_id="writer-A", writer_epoch=epoch)[-1]["hash"]
    request = {"reconciliation_id": "crash-resolution", "fill_id": obs["fill_id"],
               "incident_hash": original, "evidence_id": ref["evidence_id"],
               "evidence_sha256": ref["sha256"], "expected_head_hash": head,
               "decision": "VERIFIED_EXECUTION"}
    ledger.close()
    child = """import json,os,sys
from signal_desk.paper.ledger import PaperLedger
ledger=PaperLedger.open(sys.argv[1])
def crash(**kwargs):
    os._exit(37)
ledger._append_incident_resolution=crash
ledger.reconcile_incident(json.loads(sys.argv[2]),writer_id='writer-A',writer_epoch=1)
"""
    result = subprocess.run([sys.executable, "-c", child, str(path), json.dumps(request)], capture_output=True)
    assert result.returncode == 37, result.stderr
    recovered = PaperLedger.open(path)
    assert recovered.pending_incidents(writer_id="writer-A", writer_epoch=epoch)[0]["event"] == obs
    assert recovered.snapshot()["cash_actual_usdt"] == "100"
    assert recovered.snapshot()["cash_reserved_usdt"] == "21"
    assert recovered.reconcile_incident(request, writer_id="writer-A", writer_epoch=epoch)["status"] == "VERIFIED_EXECUTION"
    recovered.close()


def test_failed_reconciliation_rollback_halts_and_retains_both_errors(tmp_path, monkeypatch):
    from test_paper_execution import _RollbackFaultConnection
    path, ledger, epoch, iid = fixture(tmp_path)
    ref = register(ledger, seal(iid))
    obs, _, original = incident(ledger, iid)
    def fail(**kwargs):
        raise OSError("synthetic resolution write failure")
    monkeypatch.setattr(ledger, "_append_incident_resolution", fail)
    monkeypatch.setattr(ledger, "_conn", _RollbackFaultConnection(ledger._conn))
    with pytest.raises(PaperStorageError, match="rollback") as caught:
        resolve(ledger, obs["fill_id"], original, ref, decision="VERIFIED_NONEXECUTION")
    failures = caught.value.__cause__
    assert isinstance(failures, BaseExceptionGroup)
    assert isinstance(failures.exceptions[0], OSError)
    assert isinstance(failures.exceptions[1], sqlite3.OperationalError)
    with pytest.raises(Halted):
        ledger.snapshot()
    ledger.close()
    recovered = PaperLedger.open(path)
    assert recovered.pending_incidents(writer_id="writer-A", writer_epoch=epoch)[0]["event"] == obs
    assert recovered.snapshot()["cash_reserved_usdt"] == "21"
    recovered.close()


def downgrade_empty_v4_to_v3(path):
    from signal_desk.paper.ledger import REQUIRED_TRIGGERS, V3_TRIGGERS
    with sqlite3.connect(path) as raw:
        for name in REQUIRED_TRIGGERS.keys() - V3_TRIGGERS.keys():
            raw.execute(f"DROP TRIGGER {name}")
        raw.execute("DROP TABLE resolutions")
        raw.execute("DROP TABLE evidence")
        raw.execute("UPDATE meta SET schema_version=3 WHERE id=1")


def test_explicit_v3_migration_preserves_original_incident_and_reservations(tmp_path):
    path, ledger, epoch, iid = fixture(tmp_path)
    obs, result, original = incident(ledger, iid)
    before = ledger.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch)
    ledger.close()
    downgrade_empty_v4_to_v3(path)
    with pytest.raises(PaperStorageError, match="migrate_v3"):
        PaperLedger.open(path)
    migrated = PaperLedger.migrate_v3(path)
    assert migrated.pending_incidents(writer_id="writer-A", writer_epoch=epoch) == [{"event": obs, "result": result}]
    assert migrated.execution_snapshot(iid, writer_id="writer-A", writer_epoch=epoch) == before
    assert migrated.ledger_entries(writer_id="writer-A", writer_epoch=epoch)[-1]["hash"] == original
    migrated.close()
    with pytest.raises(PaperStorageError, match="Only verified schema v3"):
        PaperLedger.migrate_v3(path)


def test_v3_migration_rejects_corrupt_source_without_replacing_it(tmp_path):
    path, ledger, epoch, iid = fixture(tmp_path)
    ledger.close()
    downgrade_empty_v4_to_v3(path)
    with sqlite3.connect(path) as raw:
        raw.execute("UPDATE meta SET cash_reserved='999' WHERE id=1")
    with pytest.raises(PaperStorageError):
        PaperLedger.migrate_v3(path)
    with sqlite3.connect(path) as raw:
        assert raw.execute("SELECT schema_version,cash_reserved FROM meta").fetchone() == (3, "999")
        assert raw.execute("SELECT count(*) FROM sqlite_master WHERE name='evidence'").fetchone()[0] == 0


def test_replay_rejects_reordered_post_incident_registration_even_if_rehashed(tmp_path):
    path, ledger, epoch, iid = fixture(tmp_path)
    ref = register(ledger, seal(iid))
    obs, _, original = incident(ledger, iid)
    resolve(ledger, obs["fill_id"], original, ref, decision="VERIFIED_NONEXECUTION")
    ledger.close()
    def move_registration(entries):
        registration = next(e for e in entries if e["entry_type"] == "evidence_registered")
        entries.remove(registration)
        index = next(n for n, e in enumerate(entries) if e["entry_type"] == "reconcile")
        entries.insert(index + 1, registration)
        return entries
    rewrite_synthetic_history(path, move_registration)
    with pytest.raises(PaperStorageError, match="evidence|order|incident"):
        PaperLedger.open(path)


def test_negative_cash_is_preserved_not_silently_clamped(tmp_path):
    path, ledger, epoch, iid = fixture(tmp_path)
    journal = execution(iid, "synthetic-fill-1", price="3000")
    ref = register(ledger, journal)
    obs, _, original = incident(ledger, iid, price="3000")
    resolve(ledger, obs["fill_id"], original, ref)
    assert ledger.snapshot()["cash_actual_usdt"] == "-20.08"
    assert ledger.snapshot()["cash_deficit_usdt"] == "32.68"
    ledger.close()
    reopened = PaperLedger.open(path)
    assert reopened.snapshot()["cash_actual_usdt"] == "-20.08"
    reopened.close()


def test_final_seal_requires_consistent_source_and_coverage(tmp_path):
    path, ledger, epoch, iid = fixture(tmp_path)
    register(ledger, execution(iid, "other-fill", when=9))
    with pytest.raises(ReconciliationRequired):
        register(ledger, seal(iid, ["ev-1"], when=5))
    with pytest.raises(ReconciliationRequired):
        register(ledger, {**seal(iid, ["ev-1"], when=10), "source_identity": "unrelated-source"})
    assert register(ledger, seal(iid, ["ev-1"], when=10))["evidence_id"] == "seal-1"
    ledger.close()


def test_registration_after_execution_resolution_cannot_rewrite_proof(tmp_path):
    path, ledger, epoch, iid = fixture(tmp_path)
    ref = register(ledger, execution(iid, "synthetic-fill-1"))
    obs, _, original = incident(ledger, iid)
    resolve(ledger, obs["fill_id"], original, ref)
    later = {**execution(iid, obs["fill_id"], evidence_id="late-after-closure",
                         source_execution_id="exec-2"), "source_sequence": 2}
    with pytest.raises(ReconciliationRequired):
        register(ledger, later)
    ledger.close()
    PaperLedger.open(path).close()


def test_replay_rejects_rehashed_evidence_registration_identity(tmp_path):
    path, ledger, epoch, iid = fixture(tmp_path)
    register(ledger, execution(iid, "synthetic-fill-1"))
    ledger.close()
    def alter(entries):
        assert entries[-1]["entry_type"] == "evidence_registered"
        entries[-1]["ledger_id"] = "forged-registration"
        return entries
    rewrite_synthetic_history(path, alter)
    with pytest.raises(PaperStorageError, match="registration|identity"):
        PaperLedger.open(path)


def test_replay_reports_invalid_journal_as_storage_error(tmp_path):
    path, ledger, epoch, iid = fixture(tmp_path)
    register(ledger, execution(iid, "synthetic-fill-1"))
    ledger.close()
    def alter(entries):
        entries[-1]["evidence"]["source_sequence"] = 0
        return entries
    rewrite_synthetic_history(path, alter)
    with pytest.raises(PaperStorageError, match="journal|registration"):
        PaperLedger.open(path)
