"""First paper-only BTCUSDT intent ledger; no exchange sender or fill engine.

A successful reserve is one SQLite transaction containing immutable intent,
reservation, local-paper outbox and hash-chained ledger rows. Only committed
outbox rows are exposed. A failed/uncertain write halts this object; reopen and
verify the ledger before explicitly claiming a new writer epoch.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, InvalidOperation, ROUND_CEILING, localcontext
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from urllib.parse import quote

from signal_desk.schemas.validate import validate_json

SCHEMAS = Path(__file__).resolve().parents[3] / "schemas"
MAX_INTENTS = 2048
MAX_CLAIMS_PER_INTENT = 4
MAX_FILLS_PER_INTENT = 16
MAX_INCIDENTS_PER_INTENT = 8
MAX_EVIDENCE_PER_INTENT = 32
MAX_RESOLUTIONS_PER_INTENT = MAX_INCIDENTS_PER_INTENT
LEASE_SECONDS = 30
MAX_LEDGER_ENTRIES = (2 + MAX_CLAIMS_PER_INTENT + 2 + MAX_FILLS_PER_INTENT + 2 + MAX_INCIDENTS_PER_INTENT + MAX_EVIDENCE_PER_INTENT + MAX_RESOLUTIONS_PER_INTENT) * MAX_INTENTS
MAX_RECORD_BYTES = 4096
MAX_DB_BYTES = 64 * 1024 * 1024
MAX_WAL_BYTES = 4 * 1024 * 1024
MAX_SHM_BYTES = 1024 * 1024
PAGE_SIZE = 4096
MAX_PAGES = MAX_DB_BYTES // PAGE_SIZE
DECIMAL_PATTERN = re.compile(r"^(?:0|[1-9][0-9]{0,15})(?:\.[0-9]{1,8})?$")
IDENTITY_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
TIME_PATTERN = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z$")
REQUIRED_TRIGGERS = {
    "ledger_no_update": "CREATE TRIGGER ledger_no_update BEFORE UPDATE ON ledger BEGIN SELECT RAISE(ABORT, 'append-only ledger'); END",
    "ledger_no_delete": "CREATE TRIGGER ledger_no_delete BEFORE DELETE ON ledger BEGIN SELECT RAISE(ABORT, 'append-only ledger'); END",
    "intent_no_delete": "CREATE TRIGGER intent_no_delete BEFORE DELETE ON intents BEGIN SELECT RAISE(ABORT, 'unresolved intent'); END",
    "reservation_no_delete": "CREATE TRIGGER reservation_no_delete BEFORE DELETE ON reservations BEGIN SELECT RAISE(ABORT, 'unresolved reservation'); END",
    "outbox_no_delete": "CREATE TRIGGER outbox_no_delete BEFORE DELETE ON outbox BEGIN SELECT RAISE(ABORT, 'unresolved outbox'); END",
}
LEGACY_TRIGGERS = REQUIRED_TRIGGERS.copy()
REQUIRED_TRIGGERS.update({
    "claims_no_update": "CREATE TRIGGER claims_no_update BEFORE UPDATE ON claims BEGIN SELECT RAISE(ABORT, 'immutable claim'); END",
    "claims_no_delete": "CREATE TRIGGER claims_no_delete BEFORE DELETE ON claims BEGIN SELECT RAISE(ABORT, 'immutable claim'); END",
    "receipts_no_update": "CREATE TRIGGER receipts_no_update BEFORE UPDATE ON receipts BEGIN SELECT RAISE(ABORT, 'immutable receipt'); END",
    "receipts_no_delete": "CREATE TRIGGER receipts_no_delete BEFORE DELETE ON receipts BEGIN SELECT RAISE(ABORT, 'immutable receipt'); END",
    "acks_no_update": "CREATE TRIGGER acks_no_update BEFORE UPDATE ON acks BEGIN SELECT RAISE(ABORT, 'immutable ack'); END",
    "acks_no_delete": "CREATE TRIGGER acks_no_delete BEFORE DELETE ON acks BEGIN SELECT RAISE(ABORT, 'immutable ack'); END",
})


V2_TRIGGERS = REQUIRED_TRIGGERS.copy()
REQUIRED_TRIGGERS.update({
    "execution_no_delete": "CREATE TRIGGER execution_no_delete BEFORE DELETE ON execution BEGIN SELECT RAISE(ABORT, 'unresolved execution'); END",
    "execution_meta_no_delete": "CREATE TRIGGER execution_meta_no_delete BEFORE DELETE ON execution_meta BEGIN SELECT RAISE(ABORT, 'execution totals'); END",
    "fills_no_update": "CREATE TRIGGER fills_no_update BEFORE UPDATE ON fills BEGIN SELECT RAISE(ABORT, 'immutable fill'); END",
    "fills_no_delete": "CREATE TRIGGER fills_no_delete BEFORE DELETE ON fills BEGIN SELECT RAISE(ABORT, 'immutable fill'); END",
    "cancels_no_update": "CREATE TRIGGER cancels_no_update BEFORE UPDATE ON cancels BEGIN SELECT RAISE(ABORT, 'immutable cancel'); END",
    "cancels_no_delete": "CREATE TRIGGER cancels_no_delete BEFORE DELETE ON cancels BEGIN SELECT RAISE(ABORT, 'immutable cancel'); END",
    "incidents_no_update": "CREATE TRIGGER incidents_no_update BEFORE UPDATE ON incidents BEGIN SELECT RAISE(ABORT, 'immutable incident'); END",
    "incidents_no_delete": "CREATE TRIGGER incidents_no_delete BEFORE DELETE ON incidents BEGIN SELECT RAISE(ABORT, 'immutable incident'); END",
})
V3_TRIGGERS = REQUIRED_TRIGGERS.copy()
REQUIRED_TRIGGERS.update({
    "evidence_no_update": "CREATE TRIGGER evidence_no_update BEFORE UPDATE ON evidence BEGIN SELECT RAISE(ABORT, 'immutable evidence'); END",
    "evidence_no_delete": "CREATE TRIGGER evidence_no_delete BEFORE DELETE ON evidence BEGIN SELECT RAISE(ABORT, 'immutable evidence'); END",
    "resolutions_no_update": "CREATE TRIGGER resolutions_no_update BEFORE UPDATE ON resolutions BEGIN SELECT RAISE(ABORT, 'immutable resolution'); END",
    "resolutions_no_delete": "CREATE TRIGGER resolutions_no_delete BEFORE DELETE ON resolutions BEGIN SELECT RAISE(ABORT, 'immutable resolution'); END",
})

class PaperStorageError(RuntimeError):
    """Storage is unhealthy or its durable state cannot be trusted."""


class ReconciliationRequired(ValueError):
    """A preserved late execution correction needs explicit reconciliation."""


class Halted(PaperStorageError):
    """This object cannot admit new risk after an uncertain write."""


class DuplicateConflict(ValueError):
    """The same stable intent ID was submitted with different content."""


class StaleWriter(ValueError):
    """Writer identity or epoch no longer owns the fence."""


class StalePortfolio(ValueError):
    """The caller based a new reservation on an old portfolio version."""


class BudgetExceeded(ValueError):
    """The proposed reservation exceeds available synthetic paper budgets."""

class ClaimUnavailable(ValueError):
    """The claim is busy, expired, exhausted or not the active claim."""

class ReceiptPending(ValueError):
    """A local acceptance receipt must be reconciled, not delivered again."""


@dataclass(frozen=True)
class IntentRequest:
    strategy_id: str
    signal_id: str
    feature_snapshot_id: str
    decision_id: str
    config_version: str
    plan_hash: str
    portfolio_version: int
    decision_time: str
    valid_until: str
    expires_at: str
    qty_btc: str
    price_ceiling_usdt_per_btc: str
    fee_buffer_usdt: str
    risk_reserve_usdt: str
    intent_id: str | None = None


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(value):
    return hashlib.sha256(_json(value).encode("ascii")).hexdigest()


def _amount(value, *, positive=False):
    if type(value) is not str or len(value) > 32 or not DECIMAL_PATTERN.fullmatch(value):
        raise ValueError("Amounts must be bounded nonnegative decimal strings with explicit units")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Invalid decimal amount") from exc
    if not number.is_finite() or (positive and number <= 0):
        raise ValueError("Nonpositive or nonfinite amount")
    with localcontext() as ctx:
        # Input grammar bounds significant digits below 50. Never let a
        # caller's ambient Decimal precision round a reservation input.
        ctx.prec = 50
        return format(number.normalize(), "f")


def _time(value):
    from datetime import datetime, timezone
    if type(value) is not str or not TIME_PATTERN.fullmatch(value):
        raise ValueError("Caller-supplied event times must be UTC ISO-8601 Z")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo != timezone.utc:
        raise ValueError("Event time must be UTC")
    return parsed


def _identity(value):
    if type(value) is not str or not IDENTITY_PATTERN.fullmatch(value):
        raise ValueError("Invalid bounded stable identity")
    return value


def _prepared(request):
    if not isinstance(request, IntentRequest):
        raise ValueError("IntentRequest required")
    fields = {name: _identity(getattr(request, name)) for name in (
        "strategy_id", "signal_id", "feature_snapshot_id", "decision_id",
        "config_version", "plan_hash")}
    if type(request.portfolio_version) is not int or not 0 <= request.portfolio_version <= MAX_INTENTS:
        raise ValueError("Invalid portfolio version")
    times = {name: _time(getattr(request, name)) for name in
             ("decision_time", "valid_until", "expires_at")}
    if not times["decision_time"] <= times["valid_until"] <= times["expires_at"]:
        raise ValueError("Intent deadlines must be ordered")
    qty = _amount(request.qty_btc, positive=True)
    price = _amount(request.price_ceiling_usdt_per_btc, positive=True)
    fee = _amount(request.fee_buffer_usdt)
    risk = _amount(request.risk_reserve_usdt, positive=True)
    with localcontext() as ctx:
        ctx.prec = 50
        exact_cash = Decimal(qty) * Decimal(price) + Decimal(fee)
        cash = format(exact_cash.normalize(), "f")
        # Multiplying two 8-place inputs can require 16 fractional places;
        # never round the computed USDT reservation to the input precision.
        if exact_cash <= 0 or len(cash) > 64:
            raise ValueError("Computed cash reservation outside bound")
    identity = {"strategy_id": fields["strategy_id"], "signal_id": fields["signal_id"],
                "config_version": fields["config_version"],
                "portfolio_version": request.portfolio_version,
                "feature_snapshot_id": fields["feature_snapshot_id"],
                "decision_time": request.decision_time, "side": "buy", "qty_btc": qty,
                "plan_hash": fields["plan_hash"]}
    intent_id = "int_" + _digest(identity)
    if request.intent_id is not None and request.intent_id != intent_id:
        raise ValueError("Intent ID does not match stable identity fields")
    content = {**identity, "intent_id": intent_id,
               "decision_id": fields["decision_id"],
               "valid_until": request.valid_until, "expires_at": request.expires_at,
               "price_ceiling_usdt_per_btc": price, "fee_buffer_usdt": fee,
               "cash_reserve_usdt": cash, "risk_reserve_usdt": risk}
    fingerprint = _digest(content)
    intent = {"intent_id": intent_id, "created_ts": request.decision_time,
              "symbol": "BTCUSDT", "side": "buy", "qty": qty,
              "state": "PENDING_SEND", "fingerprint": fingerprint,
              "decision_id": fields["decision_id"],
              "portfolio_version": str(request.portfolio_version),
              "valid_until": request.valid_until, "expires_at": request.expires_at,
              "config_version": fields["config_version"],
              "risk_reservation_id": "res_" + intent_id,
              "price_ceiling_usdt_per_btc": price,
              "fee_buffer_usdt": fee, "cash_reserve_usdt": cash,
              "risk_reserve_usdt": risk, "paper_only": True,
              "destination": "local-paper-fill"}
    validate_json(intent, "order_intent.schema.json", SCHEMAS)
    if len(_json(intent).encode("ascii")) > MAX_RECORD_BYTES:
        raise ValueError("Intent record exceeds byte limit")
    return content, intent


def _decimal_text(value):
    with localcontext() as ctx:
        ctx.prec = 50
        return format(Decimal(value).normalize(), "f")


def _remaining_reserve(total, remaining, original_qty):
    if Decimal(remaining) == 0:
        return "0"
    with localcontext() as ctx:
        ctx.prec = 50
        amount = (Decimal(total) * Decimal(remaining) / Decimal(original_qty)).quantize(
            Decimal("0.0000000000000001"), rounding=ROUND_CEILING)
        return _decimal_text(min(amount, Decimal(total)))


def _initial_execution_state(intent):
    return {"status": "OPEN", "filled_qty_btc": "0", "remaining_qty_btc": intent["qty"],
            "cancelled_qty_btc": "0", "cash_reserved_usdt": intent["cash_reserve_usdt"],
            "risk_reserved_usdt": intent["risk_reserve_usdt"], "filled_risk_exposure_usdt": "0",
            "spent_usdt": "0", "fees_usdt": "0", "cancel_id": None}


def _observed_fill(event):
    required = {"fill_id", "intent_id", "fill_ts", "delta_qty_btc", "cumulative_qty_btc",
                "price_usdt_per_btc", "fee_usdt", "source_kind", "mode", "fill_reason", "assumptions"}
    if type(event) is not dict or set(event) != required or len(_json(event).encode("ascii")) > MAX_RECORD_BYTES:
        raise ValueError("Bounded explicit observed fill fields required")
    _identity(event["fill_id"]); _identity(event["intent_id"]); _time(event["fill_ts"])
    if (event["source_kind"] != "already_observed_local_paper" or
        event["mode"] not in ("conservative", "neutral", "optimistic") or
        event["fill_reason"] != "manual_reconcile"):
        raise ValueError("Only explicitly observed local-paper fill records are accepted")
    assumptions = event["assumptions"]
    if (type(assumptions) is not list or not 1 <= len(assumptions) <= 4 or
        any(type(s) is not str or not 1 <= len(s) <= 128 for s in assumptions)):
        raise ValueError("Bounded explicit fill assumptions required")
    result = dict(event)
    for key, positive in (("delta_qty_btc", True), ("cumulative_qty_btc", True),
                          ("price_usdt_per_btc", True), ("fee_usdt", False)):
        result[key] = _amount(event[key], positive=positive)
    validate_json(result, "paper_execution_event.schema.json", SCHEMAS)
    return result


def _fill_transition(state, intent, event):
    if state["status"] not in ("OPEN", "PARTIALLY_FILLED", "CANCEL_PENDING"):
        raise ReconciliationRequired("Terminal fill is a reconciliation incident")
    with localcontext() as ctx:
        ctx.prec = 50
        delta = Decimal(event["delta_qty_btc"])
        filled = Decimal(state["filled_qty_btc"]) + delta
        remaining = Decimal(state["remaining_qty_btc"]) - delta
        if remaining < 0 or filled != Decimal(event["cumulative_qty_btc"]):
            raise DuplicateConflict("Fill delta/cumulative mismatch or overfill")
        spent = Decimal(state["spent_usdt"]) + delta * Decimal(event["price_usdt_per_btc"]) + Decimal(event["fee_usdt"])
        fee_total = Decimal(state["fees_usdt"]) + Decimal(event["fee_usdt"])
        cash_reserve = _remaining_reserve(intent["cash_reserve_usdt"], remaining, intent["qty"])
        risk_reserve = _remaining_reserve(intent["risk_reserve_usdt"], remaining, intent["qty"])
        next_state = {**state, "filled_qty_btc": _decimal_text(filled),
                      "remaining_qty_btc": _decimal_text(remaining),
                      "cash_reserved_usdt": cash_reserve, "risk_reserved_usdt": risk_reserve,
                      "filled_risk_exposure_usdt": _decimal_text(Decimal(intent["risk_reserve_usdt"]) - Decimal(risk_reserve)),
                      "spent_usdt": _decimal_text(spent), "fees_usdt": _decimal_text(fee_total)}
        next_state["status"] = ("CANCEL_PENDING" if state["status"] == "CANCEL_PENDING" else
                                 "FILLED" if remaining == 0 else "PARTIALLY_FILLED")
        return next_state

def _journal_record(record):
    if type(record) is not dict or len(_json(record).encode("ascii")) > MAX_RECORD_BYTES:
        raise ValueError("Bounded synthetic private journal record required")
    common = {"evidence_id", "intent_id", "source_kind", "source_identity", "source_sequence", "kind"}
    execution = {"source_execution_id", "execution_ts", "delta_qty_btc", "price_usdt_per_btc", "fee_usdt", "observed_fill_ids"}
    seal = {"coverage_until", "execution_evidence_ids"}
    if record.get("kind") == "EXECUTION" and set(record) == common | execution:
        _identity(record["source_execution_id"]); _time(record["execution_ts"])
        for field in ("delta_qty_btc", "price_usdt_per_btc", "fee_usdt"):
            if _amount(record[field], positive=field != "fee_usdt") != record[field]:
                raise ValueError("Evidence decimals must be canonical")
        aliases = record["observed_fill_ids"]
        if type(aliases) is not list or not 1 <= len(aliases) <= 4 or len(set(aliases)) != len(aliases):
            raise ValueError("Invalid observed-fill aliases")
        for alias in aliases: _identity(alias)
    elif record.get("kind") == "FINAL_COMPLETE" and set(record) == common | seal:
        _time(record["coverage_until"])
        ids = record["execution_evidence_ids"]
        if type(ids) is not list or len(ids) > MAX_EVIDENCE_PER_INTENT or len(ids) != len(set(ids)):
            raise ValueError("Invalid complete execution set")
        for eid in ids: _identity(eid)
    else:
        raise ValueError("Invalid journal record fields")
    _identity(record["evidence_id"]); _identity(record["intent_id"]); _identity(record["source_identity"])
    if record["source_kind"] != "synthetic_private_paper_journal" or type(record["source_sequence"]) is not int or not 1 <= record["source_sequence"] <= MAX_EVIDENCE_PER_INTENT:
        raise ValueError("Synthetic source and bounded sequence required")
    validate_json(record, "paper_execution_evidence.schema.json", SCHEMAS)
    return record

def _resolution_request(request):
    keys = {"reconciliation_id", "fill_id", "incident_hash", "evidence_id", "evidence_sha256", "expected_head_hash", "decision"}
    if type(request) is not dict or set(request) != keys or len(_json(request).encode("ascii")) > MAX_RECORD_BYTES:
        raise ValueError("Bounded explicit reconciliation required")
    for key in ("reconciliation_id", "fill_id", "evidence_id"):
        _identity(request[key])
    for key in ("incident_hash", "evidence_sha256", "expected_head_hash"):
        if type(request[key]) is not str or not re.fullmatch(r"[0-9a-f]{64}", request[key]):
            raise ValueError("Invalid immutable SHA-256 reference")
    if request["decision"] not in ("VERIFIED_EXECUTION", "VERIFIED_NONEXECUTION", "VERIFIED_DUPLICATE"):
        raise ValueError("Unsupported reconciliation decision")
    validate_json(request, "paper_incident_resolution.schema.json", SCHEMAS)
    return request

def _verified_recovery_record(record, validator):
    try:
        return validator(record)
    except (ValueError, TypeError, KeyError, RuntimeError) as exc:
        raise PaperStorageError("Invalid journal or incident resolution registration") from exc

def _prove_resolution(request, incident, evidence, all_evidence, applied):
    """Structural proof only; a self-authored synthetic journal is not authenticated."""
    event = incident["event"]
    iid = event["intent_id"]
    if evidence["intent_id"] != iid:
        raise ReconciliationRequired("Evidence belongs to another intent")
    aliases = [e for e in all_evidence.values() if e["intent_id"] == iid and
               e["kind"] == "EXECUTION" and event["fill_id"] in e["observed_fill_ids"]]
    if request["decision"] == "VERIFIED_NONEXECUTION":
        if (evidence["kind"] != "FINAL_COMPLETE" or
            _time(evidence["coverage_until"]) < _time(event["fill_ts"]) or aliases or
            set(evidence["execution_evidence_ids"]) != {
                key for key, e in all_evidence.items() if e["intent_id"] == iid and e["kind"] == "EXECUTION"}):
            raise ReconciliationRequired("No complete negative execution coverage")
        # A final journal that omits a previously applied execution cannot
        # establish a closed world for this intent, even if the incident's
        # particular alias is absent. Include prior verified corrections too.
        matched_executions = set()
        for fid, prior in applied.items():
            if prior["intent_id"] != iid or _time(prior["fill_ts"]) > _time(evidence["coverage_until"]):
                continue
            matches = [source for eid, source in all_evidence.items()
                       if eid in evidence["execution_evidence_ids"] and
                       fid in source["observed_fill_ids"] and
                       (source["execution_ts"], source["delta_qty_btc"],
                        source["price_usdt_per_btc"], source["fee_usdt"]) ==
                       (prior["fill_ts"], prior["delta_qty_btc"],
                        prior["price_usdt_per_btc"], prior["fee_usdt"])]
            if len(matches) != 1 or matches[0]["source_execution_id"] in matched_executions:
                raise ReconciliationRequired("Final journal contradicts or duplicates an applied execution")
            matched_executions.add(matches[0]["source_execution_id"])
        return
    if (evidence["kind"] != "EXECUTION" or evidence not in aliases or
        any(e != evidence for e in aliases) or
        (evidence["execution_ts"], evidence["delta_qty_btc"], evidence["price_usdt_per_btc"], evidence["fee_usdt"]) !=
        (event["fill_ts"], event["delta_qty_btc"], event["price_usdt_per_btc"], event["fee_usdt"])):
        raise ReconciliationRequired("Execution record does not uniquely match original observation")
    if request["decision"] == "VERIFIED_DUPLICATE":
        others = [fid for fid in evidence["observed_fill_ids"] if fid != event["fill_id"] and fid in applied and
                  applied[fid]["intent_id"] == iid and
                  (applied[fid]["fill_ts"], applied[fid]["delta_qty_btc"], applied[fid]["price_usdt_per_btc"], applied[fid]["fee_usdt"]) ==
                  (event["fill_ts"], event["delta_qty_btc"], event["price_usdt_per_btc"], event["fee_usdt"])]
        if len(others) != 1:
            raise ReconciliationRequired("No distinct applied fill under shared source execution ID")
    elif any(fid != event["fill_id"] and fid in applied for fid in evidence["observed_fill_ids"]):
        raise ReconciliationRequired("Execution already applied under another fill ID")

def _accounting_delta(before, after):
    with localcontext() as ctx:
        ctx.prec = 50
        return {
            "cash_delta_usdt": _decimal_text(Decimal(before["spent_usdt"]) - Decimal(after["spent_usdt"])),
            "base_delta_btc": _decimal_text(Decimal(after["filled_qty_btc"]) - Decimal(before["filled_qty_btc"])),
            "cash_reserve_delta_usdt": _decimal_text(Decimal(after["cash_reserved_usdt"]) - Decimal(before["cash_reserved_usdt"])),
            "risk_reserve_delta_usdt": _decimal_text(Decimal(after["risk_reserved_usdt"]) - Decimal(before["risk_reserved_usdt"])),
            "risk_exposure_delta_usdt": _decimal_text(Decimal(after["filled_risk_exposure_usdt"]) - Decimal(before["filled_risk_exposure_usdt"])),
        }


class PaperLedger:
    def __init__(self, path, *, initial=None, allow_legacy=False):
        self.path = Path(path).absolute()
        self._allow_legacy = allow_legacy
        self._halted = False
        self._closed = False
        if self.path == Path(":memory:").absolute() or self.path.is_symlink():
            raise PaperStorageError("A trusted regular on-disk database path is required")
        parent = self.path.parent
        if not parent.is_dir() or parent.is_symlink() or parent.resolve(strict=True) != parent:
            raise PaperStorageError("Database parent must be an existing canonical directory")
        if initial is None and (not self.path.is_file() or self.path.is_symlink()):
            raise PaperStorageError("Existing paper database required")
        if initial is not None and (self.path.exists() or self.path.is_symlink()):
            raise PaperStorageError("Refusing to replace an existing paper database")
        self._bounds()
        uri = "file:" + quote(str(self.path), safe="/") + ("?mode=rwc" if initial is not None else "?mode=rw")
        self._conn = sqlite3.connect(uri, uri=True, timeout=2.5, isolation_level=None)
        try:
            if initial is not None:
                self._conn.execute(f"PRAGMA page_size={PAGE_SIZE}")
            journal = self._conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            if journal.lower() != "wal":
                raise PaperStorageError("WAL mode required")
            self._conn.execute("PRAGMA synchronous=FULL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA trusted_schema=OFF")
            self._conn.execute("PRAGMA mmap_size=0")
            self._conn.execute("PRAGMA cache_size=-4096")
            self._conn.execute("PRAGMA wal_autocheckpoint=64")
            self._conn.execute("PRAGMA journal_size_limit=1048576")
            if self._conn.execute("PRAGMA page_size").fetchone()[0] != PAGE_SIZE:
                raise PaperStorageError("Unexpected database page size")
            self._conn.execute(f"PRAGMA max_page_count={MAX_PAGES}")
            if initial is not None:
                self._initialize(*initial)
            self._verify_recovery()
        except Exception:
            self._conn.close()
            raise

    @classmethod
    def create(cls, path, *, cash_usdt, risk_budget_usdt):
        cash = _amount(cash_usdt, positive=True)
        risk = _amount(risk_budget_usdt, positive=True)
        return cls(path, initial=(cash, risk))

    @classmethod
    def open(cls, path):
        return cls(path)

    @classmethod
    def migrate_v1(cls, path):
        """Explicit atomic v1-to-v4 migration; never alter an unverified DB."""
        store = cls(path, allow_legacy=True)
        try:
            if store._meta()[0] != 1:
                raise PaperStorageError("Only verified schema v1 can be migrated")
            def migrate():
                store._verify_recovery_snapshot()
                store._install_dispatch_tables()
                store._install_execution_tables()
                store._install_reconciliation_tables()
                for name, sql in REQUIRED_TRIGGERS.items():
                    if name not in LEGACY_TRIGGERS:
                        store._conn.execute(sql)
                store._backfill_execution()
                store._conn.execute("UPDATE meta SET schema_version=4 WHERE id=1")
            store._transaction(migrate)
        finally:
            store.close()
        return cls.open(path)

    @classmethod
    def migrate_v2(cls, path):
        """Explicit verified v2-to-v4 migration preserving claims and receipts."""
        store = cls(path, allow_legacy=True)
        try:
            if store._meta()[0] != 2:
                raise PaperStorageError("Only verified schema v2 can be migrated")
            def migrate():
                store._verify_recovery_snapshot()
                store._install_execution_tables()
                store._install_reconciliation_tables()
                for name, sql in REQUIRED_TRIGGERS.items():
                    if name not in V2_TRIGGERS:
                        store._conn.execute(sql)
                store._backfill_execution()
                store._conn.execute("UPDATE meta SET schema_version=4 WHERE id=1")
            store._transaction(migrate)
        finally:
            store.close()
        return cls.open(path)

    @classmethod
    def migrate_v3(cls, path):
        """Explicit verified and atomic v3-to-v4 preservation migration."""
        store = cls(path, allow_legacy=True)
        try:
            if store._meta()[0] != 3:
                raise PaperStorageError("Only verified schema v3 can be migrated")
            def migrate():
                store._verify_recovery_snapshot()
                store._install_reconciliation_tables()
                for name in REQUIRED_TRIGGERS.keys() - V3_TRIGGERS.keys():
                    store._conn.execute(REQUIRED_TRIGGERS[name])
                store._conn.execute("UPDATE meta SET schema_version=4 WHERE id=1")
            store._transaction(migrate)
        finally:
            store.close()
        return cls.open(path)

    def close(self):
        if not self._closed:
            self._conn.close()
            self._closed = True

    def _bounds(self):
        for path, limit in ((self.path, MAX_DB_BYTES),
                            (Path(str(self.path) + "-wal"), MAX_WAL_BYTES),
                            (Path(str(self.path) + "-shm"), MAX_SHM_BYTES)):
            if path.is_symlink() or (path.exists() and
                (not path.is_file() or path.stat().st_size > limit)):
                raise PaperStorageError("Paper storage file exceeds its resource or path bound")

    def _initialize(self, cash, risk):
        self._conn.executescript("""
            BEGIN IMMEDIATE;
            CREATE TABLE meta (
                id INTEGER PRIMARY KEY CHECK (id=1), schema_version INTEGER NOT NULL,
                initial_cash TEXT NOT NULL, risk_budget TEXT NOT NULL,
                cash_reserved TEXT NOT NULL, risk_reserved TEXT NOT NULL,
                portfolio_version INTEGER NOT NULL, writer_epoch INTEGER NOT NULL,
                writer_id TEXT, last_hash TEXT);
            CREATE TABLE intents (intent_id TEXT PRIMARY KEY, content TEXT NOT NULL,
                intent_json TEXT NOT NULL, fingerprint TEXT NOT NULL, version INTEGER NOT NULL);
            CREATE TABLE reservations (intent_id TEXT PRIMARY KEY REFERENCES intents(intent_id),
                cash_usdt TEXT NOT NULL, risk_usdt TEXT NOT NULL);
            CREATE TABLE outbox (intent_id TEXT PRIMARY KEY REFERENCES intents(intent_id),
                payload TEXT NOT NULL, state TEXT NOT NULL CHECK(state='PENDING_SEND'));
            CREATE TABLE ledger (seq INTEGER PRIMARY KEY AUTOINCREMENT, ledger_id TEXT NOT NULL UNIQUE,
                payload TEXT NOT NULL, hash TEXT NOT NULL, prev_hash TEXT);
        """)
        self._install_dispatch_tables()
        self._install_execution_tables()
        self._install_reconciliation_tables()
        for sql in REQUIRED_TRIGGERS.values():
            self._conn.execute(sql)
        self._conn.execute("INSERT INTO meta VALUES(1,4,?,?, '0','0',0,0,NULL,NULL)", (cash, risk))
        self._conn.execute("INSERT INTO execution_meta VALUES(1,?, '0', '0')", (cash,))
        self._conn.commit()

    def _install_dispatch_tables(self):
        self._conn.execute("CREATE TABLE claims (intent_id TEXT NOT NULL REFERENCES outbox(intent_id),"
            "claim_version INTEGER NOT NULL CHECK(claim_version BETWEEN 1 AND 4),"
            "claim_id TEXT NOT NULL UNIQUE, envelope TEXT NOT NULL,"
            "PRIMARY KEY(intent_id,claim_version))")
        self._conn.execute("CREATE TABLE receipts (intent_id TEXT PRIMARY KEY REFERENCES outbox(intent_id),"
            "receipt TEXT NOT NULL)")
        self._conn.execute("CREATE TABLE acks (intent_id TEXT PRIMARY KEY REFERENCES receipts(intent_id),"
            "ack TEXT NOT NULL)")

    def _install_execution_tables(self):
        self._conn.execute("CREATE TABLE execution (intent_id TEXT PRIMARY KEY REFERENCES intents(intent_id),"
                           "state TEXT NOT NULL)")
        self._conn.execute("CREATE TABLE execution_meta (id INTEGER PRIMARY KEY CHECK(id=1),"
                           "cash_actual TEXT NOT NULL, base_actual TEXT NOT NULL, risk_filled TEXT NOT NULL)")
        self._conn.execute("CREATE TABLE fills (fill_id TEXT PRIMARY KEY,"
                           "intent_id TEXT NOT NULL REFERENCES intents(intent_id), payload TEXT NOT NULL)")
        self._conn.execute("CREATE TABLE cancels (intent_id TEXT NOT NULL REFERENCES intents(intent_id),"
                           "kind TEXT NOT NULL CHECK(kind IN ('requested','confirmed')), payload TEXT NOT NULL,"
                           "PRIMARY KEY(intent_id,kind))")
        self._conn.execute("CREATE TABLE incidents (fill_id TEXT PRIMARY KEY,"
                           "intent_id TEXT NOT NULL REFERENCES intents(intent_id), payload TEXT NOT NULL)")

    def _backfill_execution(self):
        cash = self._meta()[1]
        self._conn.execute("INSERT INTO execution_meta VALUES(1,?, '0', '0')", (cash,))
        for iid, text in self._conn.execute("SELECT intent_id,intent_json FROM intents"):
            self._conn.execute("INSERT INTO execution VALUES(?,?)",
                               (iid, _json(_initial_execution_state(json.loads(text)))))

    def _install_reconciliation_tables(self):
        self._conn.execute("CREATE TABLE evidence (evidence_id TEXT PRIMARY KEY,"
            "intent_id TEXT NOT NULL REFERENCES intents(intent_id), payload TEXT NOT NULL,"
            "byte_length INTEGER NOT NULL, sha256 TEXT NOT NULL)")
        self._conn.execute("CREATE TABLE resolutions (reconciliation_id TEXT PRIMARY KEY,"
            "fill_id TEXT NOT NULL UNIQUE REFERENCES incidents(fill_id), request TEXT NOT NULL,"
            "result TEXT NOT NULL)")

    def _meta(self):
        row = self._conn.execute("SELECT schema_version,initial_cash,risk_budget,cash_reserved,"
            "risk_reserved,portfolio_version,writer_epoch,writer_id,last_hash FROM meta WHERE id=1").fetchone()
        if row is None or row[0] not in (1, 2, 3, 4):
            raise PaperStorageError("Missing or unsupported paper ledger metadata")
        return row

    def _verify_recovery(self):
        self._bounds()
        # Pin all ledger and materialized reads to one WAL snapshot. A writer
        # may commit during verification without producing mixed-version reads.
        self._conn.execute("BEGIN")
        try:
            self._verify_recovery_snapshot()
            self._conn.commit()
        except BaseException:
            self._conn.rollback()
            raise
        self._bounds()

    def _verify_triggers(self):
        actual_triggers = dict(self._conn.execute(
            "SELECT name,sql FROM sqlite_master WHERE type='trigger'"))
        schema = self._meta()[0]
        expected = LEGACY_TRIGGERS if schema == 1 else (V2_TRIGGERS if schema == 2 else V3_TRIGGERS if schema == 3 else REQUIRED_TRIGGERS)
        if actual_triggers != expected:
            raise PaperStorageError("Missing or altered append-only trigger")

    def _verify_recovery_snapshot(self):
        self._verify_triggers()
        schema,cash,budget,cash_total,risk_total,version,epoch,writer,last_hash = self._meta()
        if type(version) is not int or not 0 <= version <= MAX_INTENTS or type(epoch) is not int or epoch < 0:
            raise PaperStorageError("Invalid paper ledger version or writer fence")
        rows = self._conn.execute("SELECT payload,hash,prev_hash FROM ledger ORDER BY seq LIMIT ?",
                                  (MAX_LEDGER_ENTRIES + 1,)).fetchall()
        if schema == 1 and len(rows) != 2 * version:
            raise PaperStorageError("Ledger entry count does not match portfolio version")
        if schema in (2, 3, 4) and (len(rows) < 2 * version or len(rows) > MAX_LEDGER_ENTRIES):
            raise PaperStorageError("Ledger entry count exceeds dispatch bound")
        previous = None
        created = {}
        reserved = {}
        claims = {}
        receipts = {}
        acks = {}
        execution_events = {}
        seen_incident = False
        incident_barrier = False
        evidence_history = {}
        evidence_positions = {}
        resolutions_history = {}
        incident_hashes = {}
        incident_positions = {}
        incident_intents = {}
        resolved_intents = set()
        closed_barrier = False
        for position, (text,digest,prev) in enumerate(rows):
            if len(text.encode("utf-8")) > MAX_RECORD_BYTES or prev != previous:
                raise PaperStorageError("Ledger chain or record bound failed")
            item = json.loads(text)
            if item.get("hash") != digest or _digest({k:v for k,v in item.items() if k != "hash"}) != digest:
                raise PaperStorageError("Ledger hash mismatch")
            validate_json(item, "ledger_entry.schema.json", SCHEMAS)
            iid = item["intent_id"]
            if (incident_barrier or closed_barrier) and item["entry_type"] in ("risk_reserved", "paper_fill", "cancelled"):
                raise PaperStorageError("Risk, fill or cancellation release after unresolved incident")
            if schema == 4 and item["entry_type"] == "evidence_registered":
                record = item.get("evidence")
                if (iid not in created or not isinstance(record, dict) or
                    record.get("intent_id") != iid or _verified_recovery_record(record, _journal_record) != record or
                    set(item) != {"ledger_id", "ts", "entry_type", "symbol", "config_version",
                                  "intent_id", "amounts", "evidence", "evidence_sha256",
                                  "evidence_byte_length", "prev_hash", "hash"} or
                    item["ledger_id"] != "led_" + iid + "_evidence_" + record["evidence_id"] or
                    item["ts"] != created[iid]["created_ts"] or
                    item["config_version"] != created[iid]["config_version"] or item["amounts"] != {} or
                    item.get("evidence_byte_length") != len(_json(record).encode("ascii")) or
                    item.get("evidence_sha256") != hashlib.sha256(_json(record).encode("ascii")).hexdigest()):
                    raise PaperStorageError("Invalid journal registration")
                eid = record["evidence_id"]
                prior_source = [e for e in evidence_history.values() if e["intent_id"] == iid]
                if eid in evidence_history or len(prior_source) >= MAX_EVIDENCE_PER_INTENT:
                    raise PaperStorageError("Reused or excessive evidence ID")
                if (record["source_sequence"] != len(prior_source) + 1 or
                    any(e["source_identity"] != record["source_identity"] for e in prior_source)):
                    raise PaperStorageError("Incomplete or mixed journal source sequence")
                if iid in resolved_intents:
                    raise PaperStorageError("Journal registration after intent resolution")
                if any(e["intent_id"] == iid and (e["kind"] == "FINAL_COMPLETE" or
                       (e["source_identity"] == record["source_identity"] and
                        e["source_sequence"] >= record["source_sequence"]) or
                       (e["kind"] == record["kind"] == "EXECUTION" and
                        (e["source_execution_id"] == record["source_execution_id"] or
                         not set(e["observed_fill_ids"]).isdisjoint(record["observed_fill_ids"])))) for e in evidence_history.values()):
                    raise PaperStorageError("Sealed or conflicting journal stream")
                if (record["kind"] == "EXECUTION" and any(
                    e["kind"] == "EXECUTION" and
                    e["source_identity"] == record["source_identity"] and
                    e["source_execution_id"] == record["source_execution_id"]
                    for e in evidence_history.values())):
                    raise PaperStorageError("Reused global source execution identity")
                if record["kind"] == "FINAL_COMPLETE":
                    earlier = [e for e in evidence_history.values() if e["intent_id"] == iid and e["kind"] == "EXECUTION"]
                    if (set(record["execution_evidence_ids"]) != {e["evidence_id"] for e in earlier} or
                        any(e["source_identity"] != record["source_identity"] or
                            _time(e["execution_ts"]) > _time(record["coverage_until"]) for e in earlier)):
                        raise PaperStorageError("Incomplete or contradictory journal seal")
                evidence_history[eid] = record
                evidence_positions[eid] = position
            elif schema == 4 and item["entry_type"] == "incident_resolved":
                detail = item.get("resolution")
                if (not isinstance(detail, dict) or set(detail) != {"request", "result", "state_after"} or
                    not isinstance(detail["request"], dict) or
                    _verified_recovery_record(detail["request"], _resolution_request) != detail["request"]):
                    raise PaperStorageError("Invalid incident resolution entry")
                req = detail["request"]; fid = req["fill_id"]
                if (set(item) != {"ledger_id", "ts", "entry_type", "symbol", "config_version",
                                  "intent_id", "amounts", "resolution", "prev_hash", "hash"} or
                    iid not in created or item["ledger_id"] != "led_" + iid + "_incident_resolved_" + req["reconciliation_id"] or
                    item["ts"] != created[iid]["created_ts"] or
                    item["config_version"] != created[iid]["config_version"] or
                    fid not in incident_hashes or incident_hashes[fid] != req["incident_hash"] or
                    req["evidence_id"] not in evidence_history or
                    evidence_positions.get(req["evidence_id"], position) >= incident_positions.get(fid, -1) or
                    req["evidence_sha256"] != hashlib.sha256(
                        _json(evidence_history[req["evidence_id"]]).encode("ascii")).hexdigest() or
                    req["reconciliation_id"] in resolutions_history or
                    fid in (r["request"]["fill_id"] for r in resolutions_history.values()) or
                    req["expected_head_hash"] != prev or iid != incident_intents.get(fid)):
                    raise PaperStorageError("Incident reference, evidence order or revision differs")
                resolutions_history[req["reconciliation_id"]] = detail
                execution_events.setdefault(iid, []).append(("incident_resolved", detail))
                resolved_intents.add(iid)
                closed_barrier = True
            elif item["entry_type"] == "intent_created" and iid not in created:
                created[iid] = item["intent"]
            elif item["entry_type"] == "risk_reserved" and iid in created and iid not in reserved:
                reserved[iid] = item["amounts"]
            elif (schema >= 2 and item["entry_type"] == "outbox_claimed" and
                  iid in reserved and iid not in receipts and iid not in acks):
                envelope = item.get("dispatch")
                prior_claims = claims.setdefault(iid, [])
                if (not isinstance(envelope, dict) or len(prior_claims) >= MAX_CLAIMS_PER_INTENT
                    or envelope.get("intent_id") != iid
                    or envelope.get("claim_version") != len(prior_claims) + 1
                    or item["ts"] != envelope.get("claimed_at")):
                    raise PaperStorageError("Invalid claim ledger event")
                prior_claims.append(envelope)
            elif schema >= 2 and item["entry_type"] == "local_accepted" and iid in claims and iid not in receipts:
                receipt = item.get("dispatch")
                if (not isinstance(receipt, dict) or receipt.get("intent_id") != iid
                    or item["ts"] != receipt.get("accepted_at")):
                    raise PaperStorageError("Invalid local acceptance ledger event")
                receipts[iid] = receipt
            elif schema >= 2 and item["entry_type"] == "outbox_acked" and iid in receipts and iid not in acks:
                ack = item.get("dispatch")
                if (not isinstance(ack, dict) or ack.get("intent_id") != iid
                    or ack.get("receipt_id") != receipts[iid].get("receipt_id")
                    or item["ts"] != ack.get("acked_at")):
                    raise PaperStorageError("Invalid acceptance ACK ledger event")
                acks[iid] = ack
            elif (schema >= 3 and item["entry_type"] in
                  ("paper_fill", "cancel_requested", "cancelled", "reconcile") and iid in receipts):
                detail = item.get("execution")
                if (not isinstance(detail, dict) or not isinstance(detail.get("event"), dict)
                    or not isinstance(detail.get("state_after"), dict)
                    or detail["event"].get("intent_id") != iid
                    or (item["entry_type"] != "reconcile" and "reason" in detail)
                    or (detail.get("reason") == "unresolved_incident" and not seen_incident)
                    or (item["entry_type"] == "reconcile" and "reason" in detail and
                        seen_incident and detail["reason"] != "unresolved_incident")
                    or (item["entry_type"] == "reconcile" and incident_barrier and
                        detail.get("reason") != "unresolved_incident")
                    or item["ts"] != detail["event"].get(
                        "fill_ts" if item["entry_type"] in ("paper_fill", "reconcile") else
                        "requested_at" if item["entry_type"] == "cancel_requested" else "confirmed_at")):
                    raise PaperStorageError("Invalid execution ledger event")
                execution_events.setdefault(iid, []).append((item["entry_type"], detail))
                if item["entry_type"] == "reconcile":
                    incident_hashes[detail["event"]["fill_id"]] = digest
                    incident_positions[detail["event"]["fill_id"]] = position
                    incident_intents[detail["event"]["fill_id"]] = iid
                    seen_incident = True
                    if "reason" in detail:
                        incident_barrier = True
            else:
                raise PaperStorageError("Unexpected ledger event sequence")
            previous = digest
        if previous != last_hash or len(created) != version or len(reserved) != version:
            raise PaperStorageError("Ledger chain or reservation count mismatch")
        if self._conn.execute("SELECT count(*) FROM intents").fetchone()[0] != version or \
           self._conn.execute("SELECT count(*) FROM reservations").fetchone()[0] != version or \
           self._conn.execute("SELECT count(*) FROM outbox").fetchone()[0] != version:
            raise PaperStorageError("Materialized state count mismatch")
        with localcontext() as ctx:
            ctx.prec = 50
            observed_cash = observed_risk = Decimal(0)
            for iid, intent_json, content_json, fingerprint, v in self._conn.execute(
                    "SELECT intent_id,intent_json,content,fingerprint,version FROM intents"):
                if iid not in created or json.loads(intent_json) != created[iid] or \
                   _digest(json.loads(content_json)) != fingerprint or \
                   fingerprint != created[iid]["fingerprint"] or \
                   json.loads(content_json).get("intent_id") != iid or v < 0 or v >= version:
                    raise PaperStorageError("Intent differs from ledger")
                validate_json(created[iid], "order_intent.schema.json", SCHEMAS)
                row = self._conn.execute("SELECT cash_usdt,risk_usdt FROM reservations WHERE intent_id=?", (iid,)).fetchone()
                out = self._conn.execute("SELECT payload,state FROM outbox WHERE intent_id=?", (iid,)).fetchone()
                if row is None or out is None or row != (reserved[iid]["cash_reserved_usdt"],
                        reserved[iid]["risk_reserved_usdt"]) or out != (intent_json, "PENDING_SEND"):
                    raise PaperStorageError("Reservation or pending outbox differs from ledger")
                observed_cash += Decimal(row[0]); observed_risk += Decimal(row[1])
            if schema < 3 and (observed_cash != Decimal(cash_total) or observed_risk != Decimal(risk_total)
                or observed_cash > Decimal(cash) or observed_risk > Decimal(budget)):
                raise PaperStorageError("Reserved budgets differ from ledger")
        if schema >= 2:
            execution_count = sum(map(len, execution_events.values())) + len(evidence_history)
            self._verify_dispatch_state(version, created, claims, receipts, acks, len(rows) - execution_count)
        if schema in (3, 4):
            self._verify_execution_state(created, receipts, execution_events, cash, budget,
                                         cash_total, risk_total, rows, evidence_history, resolutions_history)
            if schema == 4:
                self._verify_reconciliation_tables(evidence_history, resolutions_history)
        elif not self._allow_legacy:
            raise PaperStorageError("Schema v1/v2 requires explicit PaperLedger.migrate_v1/v2(path)")
        if schema == 3 and not self._allow_legacy:
            raise PaperStorageError("Schema v3 requires explicit PaperLedger.migrate_v3(path)")

    def _verify_dispatch_state(self, version, created, claims, receipts, acks, entry_count):
        total_claims = sum(map(len, claims.values()))
        if entry_count != 2 * version + total_claims + len(receipts) + len(acks):
            raise PaperStorageError("Dispatch ledger count mismatch")
        claim_rows = self._conn.execute(
            "SELECT intent_id,claim_version,claim_id,envelope FROM claims ORDER BY intent_id,claim_version LIMIT ?",
            (MAX_INTENTS * MAX_CLAIMS_PER_INTENT + 1,)).fetchall()
        if len(claim_rows) != total_claims:
            raise PaperStorageError("Claim count differs from ledger")
        for iid, number, claim_id, text in claim_rows:
            expected = claims.get(iid, [])
            if (number < 1 or number > len(expected) or text != _json(expected[number - 1])
                or claim_id != expected[number - 1].get("claim_id")
                or expected[number - 1].get("payload") != created.get(iid)
                or expected[number - 1].get("lease_until") !=
                    (_time(expected[number - 1]["claimed_at"]) + timedelta(seconds=LEASE_SECONDS)).isoformat().replace("+00:00", "Z")):
                raise PaperStorageError("Claim differs from ledger or intent")
            # An unreceipted pre-fix claim cannot authorize a new effect. Keep a
            # self-consistent historical receipt recoverable for later ACK.
            claimed = _time(expected[number - 1]["claimed_at"])
            if iid not in receipts and (claimed < _time(created[iid]["created_ts"]) or
                                        claimed >= _time(created[iid]["valid_until"])):
                raise PaperStorageError("Unreceipted claim chronology outside signal validity")
        receipt_rows = self._conn.execute("SELECT intent_id,receipt FROM receipts LIMIT ?",
                                          (MAX_INTENTS + 1,)).fetchall()
        ack_rows = self._conn.execute("SELECT intent_id,ack FROM acks LIMIT ?",
                                      (MAX_INTENTS + 1,)).fetchall()
        if len(receipt_rows) != len(receipts) or len(ack_rows) != len(acks):
            raise PaperStorageError("Receipt or ACK count differs from ledger")
        for iid, text in receipt_rows:
            receipt = receipts.get(iid)
            prior = claims.get(iid, [])
            if (receipt is None or text != _json(receipt) or not prior or
                prior[-1]["claim_id"] != receipt.get("claim_id") or
                prior[-1]["claim_version"] != receipt.get("claim_version") or
                not _time(prior[-1]["claimed_at"]) <= _time(receipt["accepted_at"]) < _time(prior[-1]["lease_until"]) or
                _time(receipt["accepted_at"]) > _time(created[iid]["expires_at"]) or
                receipt.get("fingerprint") != created[iid]["fingerprint"] or
                receipt.get("kind") != "ACCEPTED_NOT_FILLED" or
                receipt.get("paper_only") is not True):
                raise PaperStorageError("Local acceptance differs from claim/intent ledger")
        for iid, text in ack_rows:
            ack = acks.get(iid)
            if (ack is None or text != _json(ack) or ack.get("kind") != "ACCEPTANCE_ACK_NOT_FILL"
                or ack.get("paper_only") is not True or
                ack.get("receipt_id") != receipts[iid]["receipt_id"] or
                _time(ack["acked_at"]) < _time(receipts[iid]["accepted_at"])):
                raise PaperStorageError("ACK differs from acceptance ledger")

    def _verify_execution_state(self, created, receipts, events, cash, budget,
                                cash_total, risk_total, ledger_rows, evidence_history, resolutions_history):
        expected_fills = {}; expected_cancels = {}; expected_incidents = {}; expected_states = {}
        with localcontext() as ctx:
            ctx.prec = 50
            reserved_cash = reserved_risk = filled_risk = spent = base = Decimal(0)
            for iid, intent in created.items():
                state = _initial_execution_state(intent)
                requested = None
                latest_fill = None
                fill_count = incident_count = 0
                resolved_applied = {}
                for kind, detail in events.get(iid, []):
                    try:
                        event = detail.get("event")
                        if kind in ("paper_fill", "reconcile"):
                            if _observed_fill(event) != event or (kind == "paper_fill" and
                                _time(event["fill_ts"]) < _time(receipts[iid]["accepted_at"])):
                                raise ValueError("Noncanonical or pre-acceptance fill")
                            fid = event["fill_id"]
                            if fid in expected_fills or fid in expected_incidents:
                                raise ValueError("Reused fill identity")
                            if kind == "paper_fill":
                                fill_count += 1
                                if fill_count > MAX_FILLS_PER_INTENT:
                                    raise ValueError("Fill bound")
                                state = _fill_transition(state, intent, event)
                                fill_time = _time(event["fill_ts"])
                                latest_fill = max(latest_fill, fill_time) if latest_fill else fill_time
                                result = {"status": state["status"], "intent_id": iid, "fill_id": fid}
                                expected_fills[fid] = (iid, _json({"event": event, "result": result}))
                            else:
                                incident_count += 1
                                if incident_count > MAX_INCIDENTS_PER_INTENT:
                                    raise ValueError("Incident bound")
                                reason = detail.get("reason")
                                terminal = state["status"] in ("CANCELLED", "FILLED")
                                delta = Decimal(event["delta_qty_btc"])
                                overfill = delta > Decimal(state["remaining_qty_btc"])
                                mismatched = Decimal(state["filled_qty_btc"]) + delta != Decimal(event["cumulative_qty_btc"])
                                early = _time(event["fill_ts"]) < _time(receipts[iid]["accepted_at"])
                                if terminal:
                                    if reason not in (None, "unresolved_incident"):
                                        raise ValueError("Terminal incident reason differs")
                                elif reason != "unresolved_incident":
                                    expected_reason = (
                                        "pre_acceptance" if early else
                                        "fill_limit" if fill_count >= MAX_FILLS_PER_INTENT else
                                        "overfill" if overfill else
                                        "cumulative_mismatch" if mismatched else
                                        "accounting_limit")
                                    if reason != expected_reason:
                                        raise ValueError("Incident reason or validation precedence differs")
                                result = {"status": "RECONCILIATION_INCIDENT", "intent_id": iid, "fill_id": fid}
                                if reason is not None:
                                    result["reason"] = reason
                                expected_incidents[fid] = (iid, _json({"event": event, "result": result}))
                        elif kind == "cancel_requested":
                            if (set(event) != {"intent_id", "cancel_id", "requested_at"} or
                                event["intent_id"] != iid or requested is not None or
                                state["status"] not in ("OPEN", "PARTIALLY_FILLED")):
                                raise ValueError("Invalid cancel request")
                            _identity(event["cancel_id"]); _time(event["requested_at"])
                            if _time(event["requested_at"]) < _time(receipts[iid]["accepted_at"]):
                                raise ValueError("Cancellation precedes local acceptance")
                            requested = event
                            state = {**state, "status": "CANCEL_PENDING", "cancel_id": event["cancel_id"]}
                            result = {"status": "CANCEL_PENDING", "intent_id": iid, "cancel_id": event["cancel_id"]}
                            expected_cancels[(iid, "requested")] = _json({"event": event, "result": result})
                        elif kind == "cancelled":
                            if (set(event) != {"intent_id", "cancel_id", "confirmed_at"} or
                                event["intent_id"] != iid or requested is None or
                                state["status"] != "CANCEL_PENDING" or
                                (iid, "confirmed") in expected_cancels or
                                requested["cancel_id"] != event["cancel_id"] or
                                _time(event["confirmed_at"]) < _time(requested["requested_at"]) or
                                (latest_fill is not None and _time(event["confirmed_at"]) < latest_fill)):
                                raise ValueError("Invalid cancel confirmation")
                            state = {**state, "status": "CANCELLED" if Decimal(state["remaining_qty_btc"]) else "FILLED",
                                     "cancelled_qty_btc": state["remaining_qty_btc"],
                                     "remaining_qty_btc": "0", "cash_reserved_usdt": "0", "risk_reserved_usdt": "0"}
                            result = {"status": state["status"], "intent_id": iid, "cancel_id": event["cancel_id"]}
                            expected_cancels[(iid, "confirmed")] = _json({"event": event, "result": result})
                        elif kind == "incident_resolved":
                            request = detail["request"]
                            fid = request["fill_id"]
                            if fid not in expected_incidents or request["evidence_id"] not in evidence_history:
                                raise ValueError("Resolution precedes original incident/evidence")
                            incident = json.loads(expected_incidents[fid][1])
                            applied = {key: json.loads(value[1])["event"] for key, value in expected_fills.items()}
                            applied.update(resolved_applied)
                            _prove_resolution(request, incident, evidence_history[request["evidence_id"]],
                                              evidence_history, applied)
                            if request["decision"] == "VERIFIED_EXECUTION":
                                if (_time(incident["event"]["fill_ts"]) < _time(receipts[iid]["accepted_at"]) or
                                    fill_count >= MAX_FILLS_PER_INTENT):
                                    raise ValueError("Unsupported incident correction")
                                state = _fill_transition(state, intent, incident["event"])
                                fill_count += 1
                                resolved_applied[fid] = incident["event"]
                                latest_fill = max(latest_fill, _time(incident["event"]["fill_ts"])) if latest_fill else _time(incident["event"]["fill_ts"])
                            result = {"status": request["decision"], "fill_id": fid,
                                      "intent_id": iid, "reconciliation_id": request["reconciliation_id"]}
                            if detail["result"] != result:
                                raise ValueError("Resolution result differs")
                        else:
                            raise ValueError("Unknown execution event")
                        if detail["state_after"] != state:
                            raise ValueError("Execution event does not match reconstructed state")
                        if (Decimal(state["filled_qty_btc"]) + Decimal(state["remaining_qty_btc"]) +
                            Decimal(state["cancelled_qty_btc"]) != Decimal(intent["qty"])):
                            raise ValueError("Quantity conservation failed")
                    except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
                        raise PaperStorageError("Execution recovery event or chronology differs") from exc
                expected_states[iid] = _json(state)
                reserved_cash += Decimal(state["cash_reserved_usdt"])
                reserved_risk += Decimal(state["risk_reserved_usdt"])
                filled_risk += Decimal(state["filled_risk_exposure_usdt"])
                spent += Decimal(state["spent_usdt"])
                base += Decimal(state["filled_qty_btc"])
                if (any(Decimal(state[key]) < 0 for key in (
                    "filled_qty_btc", "remaining_qty_btc", "cancelled_qty_btc", "cash_reserved_usdt",
                    "risk_reserved_usdt", "filled_risk_exposure_usdt", "spent_usdt", "fees_usdt")) or
                    Decimal(state["risk_reserved_usdt"]) + Decimal(state["filled_risk_exposure_usdt"]) > Decimal(intent["risk_reserve_usdt"]) or
                    Decimal(state["fees_usdt"]) > Decimal(state["spent_usdt"])):
                    raise PaperStorageError("Execution inventory/risk conservation failed")
            actual_cash = Decimal(cash) - spent
            if (reserved_cash != Decimal(cash_total) or reserved_risk != Decimal(risk_total) or
                base < 0 or (not resolutions_history and
                (actual_cash < 0 or reserved_cash > actual_cash or reserved_risk + filled_risk > Decimal(budget)))):
                raise PaperStorageError("Execution cash/base/reservation totals differ")
            if self._conn.execute("SELECT count(*) FROM execution_meta").fetchone()[0] != 1 or \
               self._execution_meta() != (_decimal_text(actual_cash), _decimal_text(base), _decimal_text(filled_risk)):
                raise PaperStorageError("Execution materialized portfolio differs")
        observed_states = dict(self._conn.execute("SELECT intent_id,state FROM execution LIMIT ?",
                                                  (MAX_INTENTS + 1,)).fetchall())
        if observed_states != expected_states:
            raise PaperStorageError("Execution state differs from ledger")
        for table, expected, cols, limit in (
            ("fills", expected_fills, "fill_id,intent_id,payload", MAX_INTENTS * MAX_FILLS_PER_INTENT + 1),
            ("incidents", expected_incidents, "fill_id,intent_id,payload", MAX_INTENTS * MAX_INCIDENTS_PER_INTENT + 1)):
            rows = self._conn.execute(f"SELECT {cols} FROM {table} LIMIT ?", (limit,)).fetchall()
            if len(rows) != len(expected) or any(expected.get(fid) != (iid, text) for fid, iid, text in rows):
                raise PaperStorageError("Execution fill/incident table differs from ledger")
        cancel_rows = self._conn.execute("SELECT intent_id,kind,payload FROM cancels LIMIT ?",
                                         (2 * MAX_INTENTS + 1,)).fetchall()
        if len(cancel_rows) != len(expected_cancels) or any(
            expected_cancels.get((iid, kind)) != text for iid, kind, text in cancel_rows):
            raise PaperStorageError("Cancel history differs from ledger")
        self._verify_execution_accounting_order(ledger_rows, created, expected_states, cash,
                                                budget, cash_total, risk_total)

    def _verify_reconciliation_tables(self, evidence_history, resolutions_history):
        evidence_rows = self._conn.execute("SELECT evidence_id,intent_id,payload,byte_length,sha256 FROM evidence LIMIT ?",
                         (MAX_INTENTS * MAX_EVIDENCE_PER_INTENT + 1,)).fetchall()
        if len(evidence_rows) != len(evidence_history):
            raise PaperStorageError("Evidence count differs from ledger")
        for eid, iid, text, length, digest in evidence_rows:
            record = evidence_history.get(eid)
            if record is None or iid != record["intent_id"] or text != _json(record) or \
               length != len(text.encode("ascii")) or digest != hashlib.sha256(text.encode("ascii")).hexdigest():
                raise PaperStorageError("Immutable evidence bytes/digest differ from ledger")
        rows = self._conn.execute("SELECT reconciliation_id,fill_id,request,result FROM resolutions LIMIT ?",
                                  (MAX_INTENTS * MAX_RESOLUTIONS_PER_INTENT + 1,)).fetchall()
        if len(rows) != len(resolutions_history):
            raise PaperStorageError("Resolution count differs from ledger")
        for rid, fid, request, result in rows:
            expected = resolutions_history.get(rid)
            if expected is None or fid != expected["request"]["fill_id"] or \
               request != _json(expected["request"]) or result != _json(expected["result"]):
                raise PaperStorageError("Resolution materialization differs from ledger")

    def _verify_execution_accounting_order(self, rows, created, expected_states,
                                           cash, budget, cash_total, risk_total):
        """Recheck cost incidents against the portfolio at their ledger position."""
        with localcontext() as ctx:
            ctx.prec = 50
            actual = Decimal(cash)
            reserved_cash = reserved_risk = filled_risk = Decimal(0)
            states = {}

            def candidate(before, after, *, verified=False):
                next_cash = actual - (Decimal(after["spent_usdt"]) - Decimal(before["spent_usdt"]))
                next_reserved_cash = reserved_cash + Decimal(after["cash_reserved_usdt"]) - Decimal(before["cash_reserved_usdt"])
                next_reserved_risk = reserved_risk + Decimal(after["risk_reserved_usdt"]) - Decimal(before["risk_reserved_usdt"])
                next_filled_risk = filled_risk + Decimal(after["filled_risk_exposure_usdt"]) - Decimal(before["filled_risk_exposure_usdt"])
                if (min(next_reserved_cash, next_reserved_risk, next_filled_risk) < 0 or
                    (not verified and (next_cash < 0 or next_reserved_cash > next_cash or
                                       next_reserved_risk + next_filled_risk > Decimal(budget)))):
                    raise BudgetExceeded("Execution accounting limit")
                return next_cash, next_reserved_cash, next_reserved_risk, next_filled_risk

            for text, _, _ in rows:
                item = json.loads(text)
                iid = item["intent_id"]
                kind = item["entry_type"]
                if kind == "risk_reserved":
                    if iid in states:
                        raise PaperStorageError("Repeated execution reservation")
                    state = _initial_execution_state(created[iid])
                    states[iid] = state
                    reserved_cash += Decimal(state["cash_reserved_usdt"])
                    reserved_risk += Decimal(state["risk_reserved_usdt"])
                    if reserved_cash > actual or reserved_risk + filled_risk > Decimal(budget):
                        raise PaperStorageError("Execution reservation chronology differs")
                elif kind in ("paper_fill", "cancel_requested", "cancelled", "reconcile", "incident_resolved"):
                    if iid not in states:
                        raise PaperStorageError("Execution precedes reservation")
                    detail = item["resolution"] if kind == "incident_resolved" else item["execution"]
                    before = states[iid]
                    if kind == "reconcile":
                        if detail.get("reason") == "accounting_limit":
                            after = _fill_transition(before, created[iid], detail["event"])
                            try:
                                candidate(before, after)
                            except BudgetExceeded:
                                pass
                            else:
                                raise PaperStorageError("Accounting incident had no limit violation")
                        continue
                    after = detail["state_after"]
                    if kind == "incident_resolved" and item["amounts"] != _accounting_delta(before, after):
                        raise PaperStorageError("Resolution accounting delta differs")
                    try:
                        # A non-economic closure after a verified deficit carries zero
                        # delta. It must not be rejected for the prior shortfall.
                        actual, reserved_cash, reserved_risk, filled_risk = candidate(
                            before, after, verified=kind == "incident_resolved")
                    except BudgetExceeded as exc:
                        raise PaperStorageError("Applied execution violates accounting chronology") from exc
                    states[iid] = after
            if ({iid: _json(state) for iid, state in states.items()} != expected_states or
                reserved_cash != Decimal(cash_total) or reserved_risk != Decimal(risk_total) or
                (_decimal_text(actual), _decimal_text(filled_risk)) !=
                    (self._execution_meta()[0], self._execution_meta()[2])):
                raise PaperStorageError("Execution chronological portfolio differs from ledger")

    def _ready(self):
        if self._closed or self._halted:
            raise Halted("Paper writer closed or uncertain; reopen and reconcile")
        try:
            self._bounds()
        except PaperStorageError:
            self._halted = True
            raise

    def _append_ledger(self, *, intent, kind, amounts, previous):
        entry = {"ledger_id": "led_" + intent["intent_id"] + "_" + kind,
                 "ts": intent["created_ts"], "entry_type": kind,
                 "symbol": "BTCUSDT", "config_version": intent["config_version"],
                 "intent_id": intent["intent_id"], "amounts": amounts,
                 "prev_hash": previous}
        if kind == "intent_created":
            entry["intent"] = intent
        entry["hash"] = _digest(entry)
        validate_json(entry, "ledger_entry.schema.json", SCHEMAS)
        encoded = _json(entry)
        if len(encoded.encode("ascii")) > MAX_RECORD_BYTES:
            raise ValueError("Ledger record exceeds byte limit")
        self._conn.execute("INSERT INTO ledger(ledger_id,payload,hash,prev_hash) VALUES(?,?,?,?)",
                           (entry["ledger_id"], encoded, entry["hash"], previous))
        return entry["hash"]

    def _rollback_after_failure(self, original):
        try:
            self._conn.rollback()
        except BaseException as rollback_error:
            # An uncertain rollback is never a recoverable business rejection.
            # Retain both failures explicitly; implicit exception chaining can
            # otherwise hide the rejection that initiated the rollback.
            self._halted = True
            failures = BaseExceptionGroup(
                "Original transaction failure and rollback failure",
                [original, rollback_error])
            raise PaperStorageError(
                "Paper ledger rollback failed or uncertain; new risk blocked") from failures

    def _transaction(self, action):
        self._ready()
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            self._verify_triggers()
            result = action()
            self._conn.commit()
            self._bounds()
            return result
        except (sqlite3.Error, OSError, PaperStorageError) as exc:
            self._halted = True
            self._rollback_after_failure(exc)
            raise PaperStorageError("Paper ledger write failed or became uncertain; new risk blocked") from exc
        except Exception as exc:
            self._rollback_after_failure(exc)
            raise
        except BaseException as exc:
            # KeyboardInterrupt/SystemExit cannot leave this connection able to
            # read its own uncommitted, apparently sendable outbox rows.
            self._halted = True
            self._rollback_after_failure(exc)
            raise

    def claim_writer(self, writer_id, *, expected_epoch):
        _identity(writer_id)
        if type(expected_epoch) is not int or expected_epoch < 0:
            raise ValueError("Invalid writer epoch")
        def claim():
            epoch = self._meta()[6]
            if expected_epoch != epoch:
                raise StaleWriter("Writer epoch changed")
            self._conn.execute("UPDATE meta SET writer_epoch=?,writer_id=? WHERE id=1",
                               (epoch + 1, writer_id))
            return epoch + 1
        return self._transaction(claim)

    def reserve(self, request, *, writer_id, writer_epoch):
        content, intent = _prepared(request)
        _identity(writer_id)
        if type(writer_epoch) is not int or writer_epoch < 1:
            raise StaleWriter("Explicit claimed writer epoch required")
        content_json = _json(content)
        intent_json = _json(intent)
        def reserve_one():
            _,cash,budget,cash_total,risk_total,version,epoch,writer,prev = self._meta()
            if writer != writer_id or epoch != writer_epoch:
                raise StaleWriter("Writer fence changed")
            row = self._conn.execute("SELECT content,intent_json FROM intents WHERE intent_id=?",
                                     (intent["intent_id"],)).fetchone()
            if row is not None:
                if row != (content_json,intent_json):
                    raise DuplicateConflict("Conflicting duplicate stable intent ID")
                return {"intent_id": intent["intent_id"], "duplicate": True,
                        "outbox": json.loads(row[1])}
            if self._conn.execute("SELECT 1 FROM receipts LEFT JOIN acks USING(intent_id) "
                                  "WHERE acks.intent_id IS NULL LIMIT 1").fetchone():
                raise ReceiptPending("Reconcile local acceptance before admitting new risk")
            if self._conn.execute("SELECT 1 FROM incidents LIMIT 1").fetchone():
                raise ReconciliationRequired("Late execution incident blocks new risk")
            if request.portfolio_version != version:
                raise StalePortfolio("Portfolio version changed")
            if version >= MAX_INTENTS:
                raise BudgetExceeded("Paper intent resource bound reached; no deletion of unresolved records")
            with localcontext() as ctx:
                ctx.prec = 50
                next_cash = Decimal(cash_total) + Decimal(content["cash_reserve_usdt"])
                next_risk = Decimal(risk_total) + Decimal(content["risk_reserve_usdt"])
                actual_cash, _, filled_risk = self._execution_meta()
                if next_cash > Decimal(actual_cash) or next_risk + Decimal(filled_risk) > Decimal(budget):
                    raise BudgetExceeded("Insufficient unreserved paper cash or risk budget")
            self._conn.execute("INSERT INTO intents VALUES(?,?,?,?,?)", (intent["intent_id"],
                               content_json,intent_json,intent["fingerprint"],version))
            self._conn.execute("INSERT INTO reservations VALUES(?,?,?)", (intent["intent_id"],
                               content["cash_reserve_usdt"],content["risk_reserve_usdt"]))
            self._conn.execute("INSERT INTO outbox VALUES(?,?, 'PENDING_SEND')",
                               (intent["intent_id"],intent_json))
            self._conn.execute("INSERT INTO execution VALUES(?,?)",
                               (intent["intent_id"], _json(_initial_execution_state(intent))))
            prev = self._append_ledger(intent=intent,kind="intent_created",amounts={},previous=prev)
            prev = self._append_ledger(intent=intent,kind="risk_reserved",amounts={
                "cash_reserved_usdt": content["cash_reserve_usdt"],
                "risk_reserved_usdt": content["risk_reserve_usdt"],
                "qty_btc": content["qty_btc"],
                "price_ceiling_usdt_per_btc": content["price_ceiling_usdt_per_btc"],
                "fee_buffer_usdt": content["fee_buffer_usdt"]},previous=prev)
            self._conn.execute("UPDATE meta SET cash_reserved=?,risk_reserved=?,portfolio_version=?,"
                               "last_hash=? WHERE id=1", (format(next_cash,"f"),
                               format(next_risk,"f"),version + 1,prev))
            return {"intent_id": intent["intent_id"], "duplicate": False, "outbox": intent}
        return self._transaction(reserve_one)

    def _execution_meta(self):
        row = self._conn.execute("SELECT cash_actual,base_actual,risk_filled FROM execution_meta WHERE id=1").fetchone()
        if row is None:
            raise PaperStorageError("Missing paper execution totals")
        return row

    def snapshot(self):
        def read():
            _,cash,budget,cash_total,risk_total,version,epoch,writer,_ = self._meta()
            actual_cash, actual_base, risk_filled = self._execution_meta()
            with localcontext() as ctx:
                ctx.prec = 50
                available = _decimal_text(Decimal(actual_cash) - Decimal(cash_total))
                cash_deficit = _decimal_text(max(Decimal(0), Decimal(cash_total) - Decimal(actual_cash)))
                risk_deficit = _decimal_text(max(Decimal(0), Decimal(risk_total) + Decimal(risk_filled) - Decimal(budget)))
            return {"initial_cash_usdt": cash, "risk_budget_usdt": budget,
                    "cash_reserved_usdt": cash_total, "risk_reserved_usdt": risk_total,
                    "cash_actual_usdt": actual_cash, "base_actual_btc": actual_base,
                    "filled_risk_exposure_usdt": risk_filled,
                    "cash_available_usdt": available,
                    "cash_deficit_usdt": cash_deficit, "risk_deficit_usdt": risk_deficit,
                    "portfolio_version": version, "writer_epoch": epoch, "writer_id": writer}
        return self._transaction(read)

    def _fenced_read(self, action, *, writer_id, writer_epoch):
        _identity(writer_id)
        if type(writer_epoch) is not int or writer_epoch < 1:
            raise StaleWriter("Explicit claimed writer epoch required")
        def read():
            _, _, _, _, _, _, epoch, writer, _ = self._meta()
            if writer != writer_id or epoch != writer_epoch:
                raise StaleWriter("Writer fence changed before payload read")
            return action()
        # BEGIN IMMEDIATE serializes fence validation with the payload read.
        # Returned data is not a lease across subsequent transactions.
        return self._transaction(read)

    def pending_outbox(self, *, writer_id, writer_epoch):
        def read_pending():
            return [json.loads(row[0]) for row in self._conn.execute(
                "SELECT payload FROM outbox WHERE NOT EXISTS "
                "(SELECT 1 FROM receipts WHERE receipts.intent_id=outbox.intent_id) "
                "ORDER BY outbox.rowid LIMIT ?", (MAX_INTENTS + 1,))]
        return self._fenced_read(read_pending, writer_id=writer_id, writer_epoch=writer_epoch)

    def ledger_entries(self, *, writer_id, writer_epoch):
        def read_entries():
            return [json.loads(row[0]) for row in self._conn.execute(
                "SELECT payload FROM ledger ORDER BY seq LIMIT ?", (MAX_LEDGER_ENTRIES + 1,))]
        return self._fenced_read(read_entries, writer_id=writer_id, writer_epoch=writer_epoch)

    def _check_writer(self, writer_id, writer_epoch):
        _, _, _, _, _, _, epoch, writer, prev = self._meta()
        if writer != writer_id or epoch != writer_epoch:
            raise StaleWriter("Local writer fence changed")
        return prev

    def _append_dispatch_event(self, *, kind, intent, details, ts, suffix, previous):
        entry = {"ledger_id": "led_" + intent["intent_id"] + "_" + kind + "_" + str(suffix),
                 "ts": ts, "entry_type": kind, "symbol": "BTCUSDT",
                 "config_version": intent["config_version"], "intent_id": intent["intent_id"],
                 "amounts": {}, "dispatch": details, "prev_hash": previous}
        entry["hash"] = _digest(entry)
        validate_json(entry, "ledger_entry.schema.json", SCHEMAS)
        encoded = _json(entry)
        if len(encoded.encode("ascii")) > MAX_RECORD_BYTES:
            raise PaperStorageError("Dispatch ledger record exceeds storage bound")
        self._conn.execute("INSERT INTO ledger(ledger_id,payload,hash,prev_hash) VALUES(?,?,?,?)",
                           (entry["ledger_id"], encoded, entry["hash"], previous))
        self._conn.execute("UPDATE meta SET last_hash=? WHERE id=1", (entry["hash"],))

    def claim_outbox(self, intent_id, *, claim_id, claim_version, claimed_at,
                     writer_id, writer_epoch):
        _identity(intent_id); _identity(claim_id); _identity(writer_id)
        claimed = _time(claimed_at)
        if (type(writer_epoch) is not int or writer_epoch < 1 or
            type(claim_version) is not int or not 1 <= claim_version <= MAX_CLAIMS_PER_INTENT):
            raise ClaimUnavailable("Bounded claim version and writer epoch required")
        def claim():
            prev = self._check_writer(writer_id, writer_epoch)
            row = self._conn.execute("SELECT payload FROM outbox WHERE intent_id=?", (intent_id,)).fetchone()
            if row is None:
                raise ClaimUnavailable("Unknown committed intent")
            payload = json.loads(row[0])
            if self._conn.execute("SELECT 1 FROM acks WHERE intent_id=?", (intent_id,)).fetchone():
                raise ClaimUnavailable("Acceptance already ACKed")
            if self._conn.execute("SELECT 1 FROM receipts WHERE intent_id=?", (intent_id,)).fetchone():
                raise ReceiptPending("Reconcile existing local receipt before retry")
            lease_until = (claimed + timedelta(seconds=LEASE_SECONDS)).isoformat().replace("+00:00", "Z")
            envelope = {"intent_id": intent_id, "claim_id": claim_id,
                        "claim_version": claim_version, "writer_id": writer_id,
                        "writer_epoch": writer_epoch, "claimed_at": claimed_at,
                        "lease_until": lease_until, "payload": payload}
            if len(_json(envelope).encode("ascii")) > MAX_RECORD_BYTES:
                raise ClaimUnavailable("Claim envelope exceeds record bound")
            if claimed < _time(payload["created_ts"]) or claimed >= _time(payload["valid_until"]):
                raise ClaimUnavailable("Claim outside intent creation and signal validity window")
            prior = self._conn.execute("SELECT claim_version,envelope FROM claims WHERE intent_id=? "
                "ORDER BY claim_version DESC LIMIT 1", (intent_id,)).fetchone()
            if prior and claim_version == prior[0]:
                if prior[1] != _json(envelope):
                    raise DuplicateConflict("Conflicting duplicate claim version")
                return envelope
            if claim_version != (prior[0] + 1 if prior else 1):
                raise ClaimUnavailable("Claim version must advance by one")
            if self._conn.execute("SELECT 1 FROM claims WHERE claim_id=?", (claim_id,)).fetchone():
                raise DuplicateConflict("Claim identity already used")
            if claimed > _time(payload["expires_at"]):
                raise ClaimUnavailable("Intent waiting deadline passed")
            if prior and (claimed < _time(json.loads(prior[1])["claimed_at"]) or
                          (json.loads(prior[1])["writer_epoch"] == writer_epoch and
                           claimed < _time(json.loads(prior[1])["lease_until"]))):
                raise ClaimUnavailable("Active claim lease; expiry is not proof of delivery failure")
            # The receipt absence and writer fence are rechecked under the same
            # BEGIN IMMEDIATE transaction as this durable claim.
            self._conn.execute("INSERT INTO claims VALUES(?,?,?,?)",
                               (intent_id, claim_version, claim_id, _json(envelope)))
            self._append_dispatch_event(kind="outbox_claimed", intent=payload,
                details=envelope, ts=claimed_at, suffix=claim_version, previous=prev)
            return envelope
        return self._transaction(claim)

    def accept_local(self, envelope, *, accepted_at):
        """Local receiver boundary: validate the current fence before any effect."""
        accepted = _time(accepted_at)
        if type(envelope) is not dict or len(_json(envelope).encode("ascii")) > MAX_RECORD_BYTES:
            raise ValueError("Bounded local-paper claim envelope required")
        if set(envelope) != {"intent_id", "claim_id", "claim_version", "writer_id",
                             "writer_epoch", "claimed_at", "lease_until", "payload"}:
            raise ValueError("Invalid local claim envelope fields")
        iid = _identity(envelope["intent_id"])
        _identity(envelope["claim_id"]); _identity(envelope["writer_id"])
        _time(envelope["claimed_at"]); _time(envelope["lease_until"])
        if (type(envelope["writer_epoch"]) is not int or envelope["writer_epoch"] < 1 or
            type(envelope["claim_version"]) is not int or
            not 1 <= envelope["claim_version"] <= MAX_CLAIMS_PER_INTENT):
            raise ClaimUnavailable("Invalid claimed writer epoch or version")
        def accept():
            prev = self._check_writer(envelope["writer_id"], envelope["writer_epoch"])
            row = self._conn.execute("SELECT payload FROM outbox WHERE intent_id=?", (iid,)).fetchone()
            if row is None:
                raise ClaimUnavailable("Unknown committed intent")
            payload = json.loads(row[0])
            if envelope["payload"] != payload:
                raise DuplicateConflict("Conflicting local payload for stable intent")
            stored = self._conn.execute("SELECT envelope FROM claims WHERE intent_id=? AND claim_version=?",
                                        (iid, envelope["claim_version"])).fetchone()
            if stored is None or stored[0] != _json(envelope):
                raise DuplicateConflict("Claim identity or content differs from persisted claim")
            latest = self._conn.execute("SELECT max(claim_version) FROM claims WHERE intent_id=?",
                                        (iid,)).fetchone()[0]
            if latest != envelope["claim_version"]:
                raise ClaimUnavailable("Superseded local claim")
            prior = self._conn.execute("SELECT receipt FROM receipts WHERE intent_id=?", (iid,)).fetchone()
            if prior is not None:
                receipt = json.loads(prior[0])
                if receipt["claim_id"] != envelope["claim_id"] or receipt["claim_version"] != envelope["claim_version"]:
                    raise DuplicateConflict("Conflicting duplicate local acceptance")
                return receipt
            if (accepted < _time(payload["created_ts"]) or
                accepted >= _time(payload["valid_until"]) or
                _time(envelope["claimed_at"]) < _time(payload["created_ts"]) or
                _time(envelope["claimed_at"]) >= _time(payload["valid_until"]) or
                accepted < _time(envelope["claimed_at"]) or
                accepted >= _time(envelope["lease_until"]) or
                accepted > _time(payload["expires_at"])):
                raise ClaimUnavailable("Claim outside signal validity, lease or intent waiting window")
            receipt = {"receipt_id": "rcpt_" + iid, "intent_id": iid,
                       "claim_id": envelope["claim_id"],
                       "claim_version": envelope["claim_version"],
                       "fingerprint": payload["fingerprint"],
                       "accepted_at": accepted_at, "kind": "ACCEPTED_NOT_FILLED", "paper_only": True}
            self._conn.execute("INSERT INTO receipts VALUES(?,?)", (iid, _json(receipt)))
            self._append_dispatch_event(kind="local_accepted", intent=payload,
                details=receipt, ts=accepted_at, suffix=1, previous=prev)
            return receipt
        return self._transaction(accept)

    def reconcile_receipt(self, intent_id, *, writer_id, writer_epoch):
        _identity(intent_id)
        def read():
            row = self._conn.execute("SELECT receipt FROM receipts WHERE intent_id=?", (intent_id,)).fetchone()
            return json.loads(row[0]) if row else None
        return self._fenced_read(read, writer_id=writer_id, writer_epoch=writer_epoch)

    def ack_receipt(self, intent_id, receipt_id, *, acked_at, writer_id, writer_epoch):
        _identity(intent_id); _identity(receipt_id); _identity(writer_id)
        acked = _time(acked_at)
        if type(writer_epoch) is not int or writer_epoch < 1:
            raise StaleWriter("Claimed writer epoch required")
        def ack():
            prev = self._check_writer(writer_id, writer_epoch)
            row = self._conn.execute("SELECT receipt FROM receipts WHERE intent_id=?", (intent_id,)).fetchone()
            if row is None:
                raise ClaimUnavailable("No persisted local acceptance to ACK")
            receipt = json.loads(row[0])
            if receipt["receipt_id"] != receipt_id:
                raise DuplicateConflict("Receipt identity conflicts with persisted acceptance")
            ack_record = {"intent_id": intent_id, "receipt_id": receipt_id,
                          "acked_at": acked_at, "kind": "ACCEPTANCE_ACK_NOT_FILL",
                          "paper_only": True}
            prior = self._conn.execute("SELECT ack FROM acks WHERE intent_id=?", (intent_id,)).fetchone()
            if prior is not None:
                existing = json.loads(prior[0])
                if existing["receipt_id"] != receipt_id:
                    raise DuplicateConflict("Conflicting duplicate acceptance ACK")
                return existing
            if acked < _time(receipt["accepted_at"]):
                raise ValueError("ACK cannot precede local acceptance")
            payload = json.loads(self._conn.execute(
                "SELECT payload FROM outbox WHERE intent_id=?", (intent_id,)).fetchone()[0])
            self._conn.execute("INSERT INTO acks VALUES(?,?)", (intent_id, _json(ack_record)))
            self._append_dispatch_event(kind="outbox_acked", intent=payload,
                details=ack_record, ts=acked_at, suffix=1, previous=prev)
            return ack_record
        return self._transaction(ack)

    def _execution_row(self, intent_id):
        row = self._conn.execute("SELECT execution.state,outbox.payload FROM execution "
                                 "JOIN outbox USING(intent_id) WHERE intent_id=?", (intent_id,)).fetchone()
        if row is None:
            raise ClaimUnavailable("Unknown committed paper intent")
        return json.loads(row[0]), json.loads(row[1])

    def _update_execution(self, intent_id, before, after, *, verified=False):
        cash, base, risk_filled = self._execution_meta()
        _, _, budget, cash_reserved, risk_reserved, _, _, _, _ = self._meta()
        with localcontext() as ctx:
            ctx.prec = 50
            cash_next = Decimal(cash) - (Decimal(after["spent_usdt"]) - Decimal(before["spent_usdt"]))
            base_next = Decimal(base) + (Decimal(after["filled_qty_btc"]) - Decimal(before["filled_qty_btc"]))
            reserve_next = Decimal(cash_reserved) + Decimal(after["cash_reserved_usdt"]) - Decimal(before["cash_reserved_usdt"])
            risk_next = Decimal(risk_reserved) + Decimal(after["risk_reserved_usdt"]) - Decimal(before["risk_reserved_usdt"])
            exposure_next = Decimal(risk_filled) + Decimal(after["filled_risk_exposure_usdt"]) - Decimal(before["filled_risk_exposure_usdt"])
            if (base_next < 0 or reserve_next < 0 or risk_next < 0 or exposure_next < 0 or
                (not verified and (cash_next < 0 or reserve_next > cash_next or
                                   risk_next + exposure_next > Decimal(budget)))):
                raise BudgetExceeded("Observed fill violates cash/base/risk conservation")
        self._conn.execute("UPDATE execution SET state=? WHERE intent_id=?", (_json(after), intent_id))
        self._conn.execute("UPDATE execution_meta SET cash_actual=?,base_actual=?,risk_filled=? WHERE id=1",
                           (_decimal_text(cash_next), _decimal_text(base_next), _decimal_text(exposure_next)))
        self._conn.execute("UPDATE meta SET cash_reserved=?,risk_reserved=? WHERE id=1",
                           (_decimal_text(reserve_next), _decimal_text(risk_next)))

    def _append_execution_event(self, *, kind, intent, event, state, ts, suffix, previous, reason=None):
        execution = {"event": event, "state_after": state}
        if reason is not None:
            execution["reason"] = reason
        entry = {"ledger_id": "led_" + intent["intent_id"] + "_" + kind + "_" + suffix,
                 "ts": ts, "entry_type": kind, "symbol": "BTCUSDT",
                 "config_version": intent["config_version"], "intent_id": intent["intent_id"],
                 "amounts": {}, "execution": execution,
                 "prev_hash": previous}
        if kind in ("paper_fill", "reconcile"):
            entry["fill_id"] = event["fill_id"]
        entry["hash"] = _digest(entry)
        validate_json(entry, "ledger_entry.schema.json", SCHEMAS)
        encoded = _json(entry)
        if len(encoded.encode("ascii")) > MAX_RECORD_BYTES:
            raise PaperStorageError("Execution ledger record exceeds storage bound")
        self._conn.execute("INSERT INTO ledger(ledger_id,payload,hash,prev_hash) VALUES(?,?,?,?)",
                           (entry["ledger_id"], encoded, entry["hash"], previous))
        self._conn.execute("UPDATE meta SET last_hash=? WHERE id=1", (entry["hash"],))

    def _record_execution_incident(self, iid, intent, state, observation, previous, *, reason=None):
        count = self._conn.execute("SELECT count(*) FROM incidents WHERE intent_id=?", (iid,)).fetchone()[0]
        if count >= MAX_INCIDENTS_PER_INTENT:
            raise PaperStorageError("Observed fill incident storage bound reached; admission halted")
        result = {"status": "RECONCILIATION_INCIDENT", "intent_id": iid,
                  "fill_id": observation["fill_id"]}
        if reason is not None:
            result["reason"] = reason
        self._conn.execute("INSERT INTO incidents VALUES(?,?,?)",
                           (observation["fill_id"], iid, _json({"event": observation, "result": result})))
        self._append_execution_event(kind="reconcile", intent=intent, event=observation,
            state=state, ts=observation["fill_ts"], suffix=observation["fill_id"],
            previous=previous, reason=reason)
        return result

    def record_observed_fill(self, event, *, writer_id, writer_epoch):
        """Account for an explicitly observed local fill; never generate one."""
        observation = _observed_fill(event)
        _identity(writer_id)
        if type(writer_epoch) is not int or writer_epoch < 1:
            raise StaleWriter("Explicit claimed writer epoch required")
        iid = observation["intent_id"]
        def record():
            prev = self._check_writer(writer_id, writer_epoch)
            state, intent = self._execution_row(iid)
            for table in ("fills", "incidents"):  # fixed internal table names
                row = self._conn.execute(f"SELECT payload FROM {table} WHERE fill_id=?",
                                         (observation["fill_id"],)).fetchone()
                if row:
                    prior = json.loads(row[0])
                    if prior["event"] != observation:
                        raise DuplicateConflict("Conflicting duplicate fill identity")
                    return prior["result"]
            receipt = self._conn.execute("SELECT receipt FROM receipts WHERE intent_id=?", (iid,)).fetchone()
            if receipt is None:
                raise ClaimUnavailable("Durable local acceptance required before observing a fill")
            if self._conn.execute("SELECT 1 FROM incidents LIMIT 1").fetchone():
                return self._record_execution_incident(iid, intent, state, observation, prev,
                                                       reason="unresolved_incident")
            if state["status"] in ("CANCELLED", "FILLED"):
                return self._record_execution_incident(iid, intent, state, observation, prev)
            if _time(observation["fill_ts"]) < _time(json.loads(receipt[0])["accepted_at"]):
                return self._record_execution_incident(iid, intent, state, observation, prev,
                                                       reason="pre_acceptance")
            count = self._conn.execute("SELECT count(*) FROM fills WHERE intent_id=?", (iid,)).fetchone()[0]
            if count >= MAX_FILLS_PER_INTENT:
                return self._record_execution_incident(iid, intent, state, observation, prev,
                                                       reason="fill_limit")
            try:
                after = _fill_transition(state, intent, observation)
            except DuplicateConflict:
                reason = ("overfill" if Decimal(observation["delta_qty_btc"]) >
                          Decimal(state["remaining_qty_btc"]) else "cumulative_mismatch")
                return self._record_execution_incident(iid, intent, state, observation, prev, reason=reason)
            try:
                self._update_execution(iid, state, after)
            except BudgetExceeded:
                # _update_execution checks all conservation bounds before its first write.
                return self._record_execution_incident(iid, intent, state, observation, prev,
                                                       reason="accounting_limit")
            result = {"status": after["status"], "intent_id": iid, "fill_id": observation["fill_id"]}
            self._conn.execute("INSERT INTO fills VALUES(?,?,?)",
                               (observation["fill_id"], iid, _json({"event": observation, "result": result})))
            self._append_execution_event(kind="paper_fill", intent=intent, event=observation,
                state=after, ts=observation["fill_ts"], suffix=observation["fill_id"], previous=prev)
            return result
        return self._transaction(record)

    def request_cancel(self, intent_id, *, cancel_id, requested_at, writer_id, writer_epoch):
        _identity(intent_id); _identity(cancel_id); _identity(writer_id); _time(requested_at)
        if type(writer_epoch) is not int or writer_epoch < 1:
            raise StaleWriter("Explicit claimed writer epoch required")
        event = {"intent_id": intent_id, "cancel_id": cancel_id, "requested_at": requested_at}
        def request():
            prev = self._check_writer(writer_id, writer_epoch)
            state, intent = self._execution_row(intent_id)
            prior = self._conn.execute("SELECT payload FROM cancels WHERE intent_id=? AND kind='requested'",
                                       (intent_id,)).fetchone()
            if prior:
                stored = json.loads(prior[0])
                if stored["event"] != event:
                    raise DuplicateConflict("Conflicting cancel request")
                return stored["result"]
            accepted_row = self._conn.execute("SELECT receipt FROM receipts WHERE intent_id=?", (intent_id,)).fetchone()
            if accepted_row is None:
                raise ClaimUnavailable("Durable local acceptance required for cancellation")
            if _time(requested_at) < _time(json.loads(accepted_row[0])["accepted_at"]):
                raise ClaimUnavailable("Cancellation request precedes local acceptance")
            if state["status"] not in ("OPEN", "PARTIALLY_FILLED"):
                raise ClaimUnavailable("Cannot request cancellation of terminal/pending intent")
            after = {**state, "status": "CANCEL_PENDING", "cancel_id": cancel_id}
            self._update_execution(intent_id, state, after)
            result = {"status": "CANCEL_PENDING", "intent_id": intent_id, "cancel_id": cancel_id}
            self._conn.execute("INSERT INTO cancels VALUES(?,?,?)",
                               (intent_id, "requested", _json({"event": event, "result": result})))
            self._append_execution_event(kind="cancel_requested", intent=intent, event=event,
                state=after, ts=requested_at, suffix=cancel_id, previous=prev)
            return result
        return self._transaction(request)

    def confirm_cancel(self, intent_id, *, cancel_id, confirmed_at, writer_id, writer_epoch):
        _identity(intent_id); _identity(cancel_id); _identity(writer_id)
        confirmed = _time(confirmed_at)
        if type(writer_epoch) is not int or writer_epoch < 1:
            raise StaleWriter("Explicit claimed writer epoch required")
        event = {"intent_id": intent_id, "cancel_id": cancel_id, "confirmed_at": confirmed_at}
        def confirm():
            prev = self._check_writer(writer_id, writer_epoch)
            state, intent = self._execution_row(intent_id)
            prior = self._conn.execute("SELECT payload FROM cancels WHERE intent_id=? AND kind='confirmed'",
                                       (intent_id,)).fetchone()
            if prior:
                stored = json.loads(prior[0])
                if stored["event"] != event:
                    raise DuplicateConflict("Conflicting cancel confirmation")
                return stored["result"]
            request_row = self._conn.execute("SELECT payload FROM cancels WHERE intent_id=? AND kind='requested'",
                                             (intent_id,)).fetchone()
            if not request_row or state["status"] != "CANCEL_PENDING":
                raise ClaimUnavailable("Cancellation request is not pending")
            if self._conn.execute("SELECT 1 FROM incidents LIMIT 1").fetchone():
                raise ReconciliationRequired("Unresolved observed fill blocks cancellation release")
            requested = json.loads(request_row[0])["event"]
            if requested["cancel_id"] != cancel_id or _time(confirmed_at) < _time(requested["requested_at"]):
                raise DuplicateConflict("Cancellation identity/chronology differs")
            applied = self._conn.execute("SELECT payload FROM fills WHERE intent_id=? LIMIT ?",
                                         (intent_id, MAX_FILLS_PER_INTENT + 1)).fetchall()
            if len(applied) > MAX_FILLS_PER_INTENT:
                raise PaperStorageError("Fill count exceeds storage bound")
            if any(confirmed < _time(json.loads(row[0])["event"]["fill_ts"]) for row in applied):
                raise DuplicateConflict("Cancellation confirmation precedes recorded fill timestamp")
            after = {**state, "status": "CANCELLED" if Decimal(state["remaining_qty_btc"]) else "FILLED",
                     "cancelled_qty_btc": state["remaining_qty_btc"], "remaining_qty_btc": "0",
                     "cash_reserved_usdt": "0", "risk_reserved_usdt": "0"}
            self._update_execution(intent_id, state, after)
            result = {"status": after["status"], "intent_id": intent_id, "cancel_id": cancel_id}
            self._conn.execute("INSERT INTO cancels VALUES(?,?,?)",
                               (intent_id, "confirmed", _json({"event": event, "result": result})))
            self._append_execution_event(kind="cancelled", intent=intent, event=event,
                state=after, ts=confirmed_at, suffix=cancel_id, previous=prev)
            return result
        return self._transaction(confirm)

    def execution_snapshot(self, intent_id, *, writer_id, writer_epoch):
        _identity(intent_id)
        def read():
            state, _ = self._execution_row(intent_id)
            actual_cash, actual_base, risk_filled = self._execution_meta()
            global_cash = self._meta()[3]
            with localcontext() as ctx:
                ctx.prec = 50
                available = _decimal_text(Decimal(actual_cash) - Decimal(global_cash))
            return {**state, "intent_id": intent_id, "actual_cash_usdt": actual_cash,
                    "actual_base_btc": actual_base, "portfolio_risk_filled_usdt": risk_filled,
                    "available_cash_usdt": available}
        return self._fenced_read(read, writer_id=writer_id, writer_epoch=writer_epoch)

    def pending_incidents(self, *, writer_id, writer_epoch):
        def read():
            return [json.loads(row[0]) for row in self._conn.execute(
                "SELECT payload FROM incidents WHERE NOT EXISTS "
                "(SELECT 1 FROM resolutions WHERE resolutions.fill_id=incidents.fill_id) "
                "ORDER BY incidents.rowid LIMIT ?", (MAX_INTENTS * MAX_INCIDENTS_PER_INTENT + 1,))]
        return self._fenced_read(read, writer_id=writer_id, writer_epoch=writer_epoch)

    def _append_incident_resolution(self, *, intent, request, result, before, state, previous):
        entry = {"ledger_id": "led_" + intent["intent_id"] + "_incident_resolved_" + request["reconciliation_id"],
                 "ts": intent["created_ts"], "entry_type": "incident_resolved", "symbol": "BTCUSDT",
                 "config_version": intent["config_version"], "intent_id": intent["intent_id"],
                 "amounts": _accounting_delta(before, state),
                 "resolution": {"request": request, "result": result, "state_after": state}, "prev_hash": previous}
        entry["hash"] = _digest(entry)
        validate_json(entry, "ledger_entry.schema.json", SCHEMAS)
        text = _json(entry)
        if len(text.encode("ascii")) > MAX_RECORD_BYTES:
            raise PaperStorageError("Resolution ledger entry exceeds byte bound")
        self._conn.execute("INSERT INTO ledger(ledger_id,payload,hash,prev_hash) VALUES(?,?,?,?)",
                           (entry["ledger_id"], text, entry["hash"], previous))
        self._conn.execute("UPDATE meta SET last_hash=? WHERE id=1", (entry["hash"],))

    def register_execution_evidence(self, record, *, writer_id, writer_epoch):
        """Register synthetic-only bytes; never infer source authenticity from a digest."""
        record = _journal_record(record)
        text = _json(record)
        length = len(text.encode("ascii"))
        digest = hashlib.sha256(text.encode("ascii")).hexdigest()
        def register():
            prev = self._check_writer(writer_id, writer_epoch)
            iid = record["intent_id"]
            state, intent = self._execution_row(iid)
            old = self._conn.execute("SELECT payload,byte_length,sha256 FROM evidence WHERE evidence_id=?",
                                     (record["evidence_id"],)).fetchone()
            if old:
                if old != (text, length, digest):
                    raise DuplicateConflict("Conflicting immutable evidence ID")
                return {"evidence_id": record["evidence_id"], "sha256": digest, "byte_length": length}
            rows = [json.loads(row[0]) for row in self._conn.execute(
                "SELECT payload FROM evidence WHERE intent_id=? LIMIT ?", (iid, MAX_EVIDENCE_PER_INTENT + 1))]
            if len(rows) >= MAX_EVIDENCE_PER_INTENT:
                raise PaperStorageError("Evidence capacity exhausted")
            # This synthetic journal sequence is contiguous and scoped to one
            # intent/source. A seal cannot prove absence across a missing slot.
            if (record["source_sequence"] != len(rows) + 1 or
                any(e["source_identity"] != record["source_identity"] for e in rows)):
                raise ReconciliationRequired("Incomplete or mixed journal source sequence")
            if any(e["kind"] == "FINAL_COMPLETE" for e in rows):
                raise ReconciliationRequired("Sealed intent rejects further journal records")
            if self._conn.execute("SELECT 1 FROM resolutions JOIN incidents USING(fill_id) "
                                  "WHERE incidents.intent_id=? LIMIT 1", (iid,)).fetchone():
                raise ReconciliationRequired("Resolved intent rejects further journal records")
            if any(e["source_identity"] == record["source_identity"] and
                   e["source_sequence"] >= record["source_sequence"] for e in rows):
                raise DuplicateConflict("Journal sequence must advance per source")
            if record["kind"] == "EXECUTION" and any(e["kind"] == "EXECUTION" and
                (e["source_execution_id"] == record["source_execution_id"] or
                 not set(e["observed_fill_ids"]).isdisjoint(record["observed_fill_ids"])) for e in rows):
                raise DuplicateConflict("Source execution identity or observed-fill alias reused")
            if record["kind"] == "EXECUTION":
                # Source execution identity is global within a journal source,
                # not reusable under a second paper intent.
                for (source_text,) in self._conn.execute(
                        "SELECT payload FROM evidence LIMIT ?", (MAX_INTENTS * MAX_EVIDENCE_PER_INTENT + 1,)):
                    source = json.loads(source_text)
                    if (source["kind"] == "EXECUTION" and
                        source["source_identity"] == record["source_identity"] and
                        source["source_execution_id"] == record["source_execution_id"]):
                        raise DuplicateConflict("Source execution identity reused across intents")
            if record["kind"] == "FINAL_COMPLETE" and (
                set(record["execution_evidence_ids"]) != {
                    e["evidence_id"] for e in rows if e["kind"] == "EXECUTION"} or
                any(e["source_identity"] != record["source_identity"] or
                    _time(e["execution_ts"]) > _time(record["coverage_until"])
                    for e in rows if e["kind"] == "EXECUTION")):
                raise ReconciliationRequired("Final journal seal has incomplete or contradictory coverage")
            self._conn.execute("INSERT INTO evidence VALUES(?,?,?,?,?)",
                               (record["evidence_id"], iid, text, length, digest))
            entry = {"ledger_id": "led_" + iid + "_evidence_" + record["evidence_id"],
                     "ts": intent["created_ts"], "entry_type": "evidence_registered",
                     "symbol": "BTCUSDT", "config_version": intent["config_version"], "intent_id": iid,
                     "amounts": {}, "evidence": record, "evidence_sha256": digest,
                     "evidence_byte_length": length, "prev_hash": prev}
            entry["hash"] = _digest(entry)
            validate_json(entry, "ledger_entry.schema.json", SCHEMAS)
            encoded = _json(entry)
            if len(encoded.encode("ascii")) > MAX_RECORD_BYTES:
                raise PaperStorageError("Evidence ledger entry exceeds byte bound")
            self._conn.execute("INSERT INTO ledger(ledger_id,payload,hash,prev_hash) VALUES(?,?,?,?)",
                               (entry["ledger_id"], encoded, entry["hash"], prev))
            self._conn.execute("UPDATE meta SET last_hash=? WHERE id=1", (entry["hash"],))
            return {"evidence_id": record["evidence_id"], "sha256": digest, "byte_length": length}
        return self._transaction(register)

    def reconcile_incident(self, request, *, writer_id, writer_epoch):
        """Explicit synthetic-only structural proof; closure never restores readiness."""
        request = _resolution_request(request)
        def resolve():
            prev = self._check_writer(writer_id, writer_epoch)
            old = self._conn.execute("SELECT request,result FROM resolutions WHERE reconciliation_id=?",
                                     (request["reconciliation_id"],)).fetchone()
            if old:
                if old[0] != _json(request):
                    raise DuplicateConflict("Conflicting immutable reconciliation ID")
                return json.loads(old[1])
            if request["expected_head_hash"] != prev:
                raise ReconciliationRequired("Stale ledger-head state revision")
            row = self._conn.execute("SELECT intent_id,payload FROM incidents WHERE fill_id=?",
                                     (request["fill_id"],)).fetchone()
            if not row:
                raise ReconciliationRequired("Unknown original incident")
            iid, text = row
            if self._conn.execute("SELECT 1 FROM resolutions WHERE fill_id=?", (request["fill_id"],)).fetchone():
                raise DuplicateConflict("Incident already resolved under another ID")
            original = self._conn.execute("SELECT payload FROM ledger WHERE hash=?",
                                          (request["incident_hash"],)).fetchone()
            if not original or json.loads(original[0]).get("entry_type") != "reconcile" or \
               json.loads(original[0]).get("fill_id") != request["fill_id"] or \
               json.loads(original[0]).get("intent_id") != iid:
                raise ReconciliationRequired("Original incident hash does not identify this incident")
            evidence_row = self._conn.execute("SELECT payload,sha256,byte_length FROM evidence WHERE evidence_id=?",
                                             (request["evidence_id"],)).fetchone()
            if not evidence_row or evidence_row[1] != request["evidence_sha256"]:
                raise ReconciliationRequired("Missing or mismatched precommitted evidence")

            incident_seq = self._conn.execute("SELECT seq FROM ledger WHERE hash=?", (request["incident_hash"],)).fetchone()[0]
            committed = [json.loads(p) for seq, p in self._conn.execute(
                "SELECT seq,payload FROM ledger WHERE seq<? ORDER BY seq", (incident_seq,))]
            if not any(e["entry_type"] == "evidence_registered" and
                       e["evidence"]["evidence_id"] == request["evidence_id"] and
                       e["evidence_sha256"] == evidence_row[1] for e in committed):
                raise ReconciliationRequired("Evidence was not committed before original incident")
            evidence = json.loads(evidence_row[0]); original_incident = json.loads(text)
            all_evidence = {eid: json.loads(payload) for eid, payload in self._conn.execute(
                "SELECT evidence_id,payload FROM evidence LIMIT ?", (MAX_INTENTS * MAX_EVIDENCE_PER_INTENT + 1,))}
            applied = {fid: json.loads(payload)["event"] for fid, payload in self._conn.execute(
                "SELECT fill_id,payload FROM fills LIMIT ?", (MAX_INTENTS * MAX_FILLS_PER_INTENT + 1,))}
            verified_count = 0
            for (past_request,) in self._conn.execute(
                    "SELECT request FROM resolutions LIMIT ?", (MAX_INTENTS * MAX_RESOLUTIONS_PER_INTENT + 1,)):
                previous = json.loads(past_request)
                if previous["decision"] == "VERIFIED_EXECUTION":
                    source = self._conn.execute("SELECT payload FROM incidents WHERE fill_id=?",
                                                (previous["fill_id"],)).fetchone()
                    if source is None:
                        raise PaperStorageError("Verified execution lost its original incident")
                    prior_event = json.loads(source[0])["event"]
                    applied[previous["fill_id"]] = prior_event
                    if prior_event["intent_id"] == iid:
                        verified_count += 1
            _prove_resolution(request, original_incident, evidence, all_evidence, applied)
            state, intent = self._execution_row(iid)
            if request["decision"] == "VERIFIED_EXECUTION":
                event = original_incident["event"]
                receipt = json.loads(self._conn.execute("SELECT receipt FROM receipts WHERE intent_id=?", (iid,)).fetchone()[0])
                if (_time(event["fill_ts"]) < _time(receipt["accepted_at"]) or
                    state["status"] not in ("OPEN", "PARTIALLY_FILLED", "CANCEL_PENDING") or
                    verified_count + self._conn.execute("SELECT count(*) FROM fills WHERE intent_id=?", (iid,)).fetchone()[0] >= MAX_FILLS_PER_INTENT):
                    raise ReconciliationRequired("Unsupported terminal, early or full fill correction")
                try:
                    after = _fill_transition(state, intent, event)
                except (DuplicateConflict, ReconciliationRequired) as exc:
                    raise ReconciliationRequired("Unsupported quantity or cumulative correction") from exc
                self._update_execution(iid, state, after, verified=True)
            else:
                after = state
            result = {"status": request["decision"], "fill_id": request["fill_id"],
                      "intent_id": iid, "reconciliation_id": request["reconciliation_id"]}
            self._conn.execute("INSERT INTO resolutions VALUES(?,?,?,?)",
                               (request["reconciliation_id"], request["fill_id"], _json(request), _json(result)))
            self._append_incident_resolution(intent=intent, request=request, result=result,
                                             before=state, state=after, previous=prev)
            return result
        return self._transaction(resolve)
