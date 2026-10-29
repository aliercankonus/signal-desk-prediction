"""First paper-only BTCUSDT intent ledger; no exchange sender or fill engine.

A successful reserve is one SQLite transaction containing immutable intent,
reservation, local-paper outbox and hash-chained ledger rows. Only committed
outbox rows are exposed. A failed/uncertain write halts this object; reopen and
verify the ledger before explicitly claiming a new writer epoch.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, InvalidOperation, localcontext
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
LEASE_SECONDS = 30
MAX_LEDGER_ENTRIES = (2 + MAX_CLAIMS_PER_INTENT + 2) * MAX_INTENTS
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


class PaperStorageError(RuntimeError):
    """Storage is unhealthy or its durable state cannot be trusted."""


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
        """Explicit atomic v1-to-v2 migration; never alter an unverified DB."""
        store = cls(path, allow_legacy=True)
        try:
            if store._meta()[0] != 1:
                raise PaperStorageError("Only verified schema v1 can be migrated")
            def migrate():
                store._verify_recovery_snapshot()
                store._install_dispatch_tables()
                for name, sql in REQUIRED_TRIGGERS.items():
                    if name not in LEGACY_TRIGGERS:
                        store._conn.execute(sql)
                store._conn.execute("UPDATE meta SET schema_version=2 WHERE id=1")
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
        for sql in REQUIRED_TRIGGERS.values():
            self._conn.execute(sql)
        self._conn.execute("INSERT INTO meta VALUES(1,2,?,?, '0','0',0,0,NULL,NULL)", (cash, risk))
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

    def _meta(self):
        row = self._conn.execute("SELECT schema_version,initial_cash,risk_budget,cash_reserved,"
            "risk_reserved,portfolio_version,writer_epoch,writer_id,last_hash FROM meta WHERE id=1").fetchone()
        if row is None or row[0] not in (1, 2):
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
        expected = LEGACY_TRIGGERS if self._meta()[0] == 1 else REQUIRED_TRIGGERS
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
        if schema == 2 and (len(rows) < 2 * version or len(rows) > MAX_LEDGER_ENTRIES):
            raise PaperStorageError("Ledger entry count exceeds dispatch bound")
        previous = None
        created = {}
        reserved = {}
        claims = {}
        receipts = {}
        acks = {}
        for text,digest,prev in rows:
            if len(text.encode("utf-8")) > MAX_RECORD_BYTES or prev != previous:
                raise PaperStorageError("Ledger chain or record bound failed")
            item = json.loads(text)
            if item.get("hash") != digest or _digest({k:v for k,v in item.items() if k != "hash"}) != digest:
                raise PaperStorageError("Ledger hash mismatch")
            validate_json(item, "ledger_entry.schema.json", SCHEMAS)
            iid = item["intent_id"]
            if item["entry_type"] == "intent_created" and iid not in created:
                created[iid] = item["intent"]
            elif item["entry_type"] == "risk_reserved" and iid in created and iid not in reserved:
                reserved[iid] = item["amounts"]
            elif (schema == 2 and item["entry_type"] == "outbox_claimed" and
                  iid in reserved and iid not in receipts and iid not in acks):
                envelope = item.get("dispatch")
                prior_claims = claims.setdefault(iid, [])
                if (not isinstance(envelope, dict) or len(prior_claims) >= MAX_CLAIMS_PER_INTENT
                    or envelope.get("intent_id") != iid
                    or envelope.get("claim_version") != len(prior_claims) + 1
                    or item["ts"] != envelope.get("claimed_at")):
                    raise PaperStorageError("Invalid claim ledger event")
                prior_claims.append(envelope)
            elif schema == 2 and item["entry_type"] == "local_accepted" and iid in claims and iid not in receipts:
                receipt = item.get("dispatch")
                if (not isinstance(receipt, dict) or receipt.get("intent_id") != iid
                    or item["ts"] != receipt.get("accepted_at")):
                    raise PaperStorageError("Invalid local acceptance ledger event")
                receipts[iid] = receipt
            elif schema == 2 and item["entry_type"] == "outbox_acked" and iid in receipts and iid not in acks:
                ack = item.get("dispatch")
                if (not isinstance(ack, dict) or ack.get("intent_id") != iid
                    or ack.get("receipt_id") != receipts[iid].get("receipt_id")
                    or item["ts"] != ack.get("acked_at")):
                    raise PaperStorageError("Invalid acceptance ACK ledger event")
                acks[iid] = ack
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
            if (observed_cash != Decimal(cash_total) or observed_risk != Decimal(risk_total)
                or observed_cash > Decimal(cash) or observed_risk > Decimal(budget)):
                raise PaperStorageError("Reserved budgets differ from ledger")
        if schema == 2:
            self._verify_dispatch_state(version, created, claims, receipts, acks, len(rows))
        elif not self._allow_legacy:
            raise PaperStorageError("Schema v1 requires explicit PaperLedger.migrate_v1(path)")

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
            if request.portfolio_version != version:
                raise StalePortfolio("Portfolio version changed")
            if version >= MAX_INTENTS:
                raise BudgetExceeded("Paper intent resource bound reached; no deletion of unresolved records")
            with localcontext() as ctx:
                ctx.prec = 50
                next_cash = Decimal(cash_total) + Decimal(content["cash_reserve_usdt"])
                next_risk = Decimal(risk_total) + Decimal(content["risk_reserve_usdt"])
                if next_cash > Decimal(cash) or next_risk > Decimal(budget):
                    raise BudgetExceeded("Insufficient unreserved paper cash or risk budget")
            self._conn.execute("INSERT INTO intents VALUES(?,?,?,?,?)", (intent["intent_id"],
                               content_json,intent_json,intent["fingerprint"],version))
            self._conn.execute("INSERT INTO reservations VALUES(?,?,?)", (intent["intent_id"],
                               content["cash_reserve_usdt"],content["risk_reserve_usdt"]))
            self._conn.execute("INSERT INTO outbox VALUES(?,?, 'PENDING_SEND')",
                               (intent["intent_id"],intent_json))
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

    def snapshot(self):
        self._ready()
        _,cash,budget,cash_total,risk_total,version,epoch,writer,_ = self._meta()
        return {"initial_cash_usdt": cash, "risk_budget_usdt": budget,
                "cash_reserved_usdt": cash_total, "risk_reserved_usdt": risk_total,
                "portfolio_version": version, "writer_epoch": epoch, "writer_id": writer}

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
