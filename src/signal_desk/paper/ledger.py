"""First paper-only BTCUSDT intent ledger; no exchange sender or fill engine.

A successful reserve is one SQLite transaction containing immutable intent,
reservation, local-paper outbox and hash-chained ledger rows. Only committed
outbox rows are exposed. A failed/uncertain write halts this object; reopen and
verify the ledger before explicitly claiming a new writer epoch.
"""
from __future__ import annotations

from dataclasses import dataclass
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
    def __init__(self, path, *, initial=None):
        self.path = Path(path).absolute()
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
        for sql in REQUIRED_TRIGGERS.values():
            self._conn.execute(sql)
        self._conn.execute("INSERT INTO meta VALUES(1,1,?,?, '0','0',0,0,NULL,NULL)", (cash, risk))
        self._conn.commit()

    def _meta(self):
        row = self._conn.execute("SELECT schema_version,initial_cash,risk_budget,cash_reserved,"
            "risk_reserved,portfolio_version,writer_epoch,writer_id,last_hash FROM meta WHERE id=1").fetchone()
        if row is None or row[0] != 1:
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
        if actual_triggers != REQUIRED_TRIGGERS:
            raise PaperStorageError("Missing or altered append-only trigger")

    def _verify_recovery_snapshot(self):
        self._verify_triggers()
        schema,cash,budget,cash_total,risk_total,version,epoch,writer,last_hash = self._meta()
        if type(version) is not int or not 0 <= version <= MAX_INTENTS or type(epoch) is not int or epoch < 0:
            raise PaperStorageError("Invalid paper ledger version or writer fence")
        rows = self._conn.execute("SELECT payload,hash,prev_hash FROM ledger ORDER BY seq LIMIT ?",
                                  (2 * MAX_INTENTS + 1,)).fetchall()
        if len(rows) != 2 * version:
            raise PaperStorageError("Ledger entry count does not match portfolio version")
        previous = None
        created = {}
        reserved = {}
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
                "SELECT payload FROM outbox WHERE state='PENDING_SEND' ORDER BY rowid LIMIT ?",
                (MAX_INTENTS + 1,))]
        return self._fenced_read(read_pending, writer_id=writer_id, writer_epoch=writer_epoch)

    def ledger_entries(self, *, writer_id, writer_epoch):
        def read_entries():
            return [json.loads(row[0]) for row in self._conn.execute(
                "SELECT payload FROM ledger ORDER BY seq LIMIT ?", (2 * MAX_INTENTS + 1,))]
        return self._fenced_read(read_entries, writer_id=writer_id, writer_epoch=writer_epoch)
