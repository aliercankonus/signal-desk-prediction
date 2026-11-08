"""Dormant #41 one-entry lifecycle core. No production backend or GO entry is wired.

A later operator-reviewed backend must supply the bounded host/container actions.
The core journals each effect intent before calling that backend, never resumes a
previous attempt, and only cleans exact IDs returned and journaled by the backend.
"""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import stat
import time
from typing import Protocol


ID = re.compile(r"[a-zA-Z0-9_.:-]{1,128}\Z")
PHASES = ("preflight", "login", "github_reads", "enroll_disabled", "enable_scheduler",
          "one_bridge_claim", "reconcile", "cleanup", "report")
MAX_JOURNAL = 16384


@dataclass(frozen=True)
class Owned:
    kind: str
    ident: str
    proof: str

    def __post_init__(self):
        if self.kind not in {"worker", "proxy", "network", "firewall", "scheduler", "enrollment"}:
            raise ValueError("unrecognized resource kind")
        if not ID.fullmatch(self.ident) or not ID.fullmatch(self.proof):
            raise ValueError("unbounded resource identity")


class Operations(Protocol):
    """Every implementation must impose independent per-stage deadlines."""

    def preflight(self) -> None: ...
    def login(self) -> None: ...
    def github_reads(self) -> None: ...
    def enroll_disabled(self) -> tuple[Owned, ...]: ...
    def enable_scheduler(self) -> tuple[Owned, ...]: ...
    def one_bridge_claim(self) -> tuple[Owned, ...]: ...
    def reconcile(self) -> str: ...
    def inspect_owned(self, resources: tuple[Owned, ...]) -> bool: ...
    def cleanup(self, resources: tuple[Owned, ...]) -> tuple[Owned, ...]: ...
    def cleanup_readback(self, resources: tuple[Owned, ...]) -> bool: ...
    def report(self, sanitized: dict) -> str: ...
    def report_readback(self, receipt: str, sanitized: dict) -> bool: ...


class Journal:
    def __init__(self, directory: Path, attempt: str):
        if not ID.fullmatch(attempt):
            raise ValueError("invalid attempt identity")
        self.directory = directory
        self.attempt = attempt
        self.file = directory / "phase.json"
        self.state = {
            "version": 1, "attempt": attempt, "phase": "created", "status": "blocked",
            "intent": None, "unresolved_effect": None, "owned": [], "cleanup_verified": False,
            "report_receipt": None,
        }

    def _private_parent(self):
        for parent in self.directory.parents:
            info = parent.lstat()
            if (not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o022 or
                    info.st_uid not in (0, os.geteuid())):
                raise PermissionError("journal ancestor is writable or foreign-owned")

    def _private(self):
        self._private_parent()
        if self.directory.is_symlink() or not self.directory.is_dir():
            raise PermissionError("private journal directory absent")
        info = self.directory.lstat()
        if info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise PermissionError("journal directory not private")

    def _persist(self, create=False):
        self._private()
        data = json.dumps(self.state, sort_keys=True, separators=(",", ":")).encode()
        if len(data) > MAX_JOURNAL:
            raise ValueError("journal exceeds bound")
        if not create:
            if self.file.is_symlink() or not self.file.is_file():
                raise PermissionError("journal missing or symlinked")
            info = self.file.lstat()
            if info.st_uid != os.geteuid() or info.st_mode & 0o077 or info.st_nlink != 1:
                raise PermissionError("journal inode not private")
        if create:
            fd = os.open(self.file, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        else:
            tmp = self.directory / (".phase-" + os.urandom(8).hex())
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, self.file)
        dirfd = os.open(self.directory, os.O_DIRECTORY | os.O_RDONLY | os.O_NOFOLLOW)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)

    def create(self):
        # A pre-existing directory, including a partial previous attempt, is a STOP.
        self._private_parent()
        self.directory.mkdir(mode=0o700)
        self._persist(create=True)
        parent = os.open(self.directory.parent, os.O_DIRECTORY | os.O_RDONLY | os.O_NOFOLLOW)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)

    def record(self, phase: str, *, intent=None, status=None, owned=None, cleanup=None,
               receipt=None, unresolved=None):
        if phase not in PHASES and phase != "blocked":
            raise ValueError("unreviewed phase")
        self.state["phase"] = phase
        self.state["intent"] = intent
        if unresolved is not None:
            if unresolved not in ("enroll_disabled", "enable_scheduler", "one_bridge_claim", "cleanup", "report"):
                raise ValueError("unreviewed unresolved effect")
            self.state["unresolved_effect"] = unresolved
        if status is not None:
            self.state["status"] = status
        if owned is not None:
            self.state["owned"] = [x.__dict__ for x in owned]
        if cleanup is not None:
            self.state["cleanup_verified"] = cleanup
        if receipt is not None:
            if not isinstance(receipt, str) or not ID.fullmatch(receipt):
                raise ValueError("invalid report receipt")
            self.state["report_receipt"] = receipt
        self._persist()


def run_once(journal: Journal, ops: Operations, *, deadline: float,
             clock=time.monotonic) -> dict:
    """One in-memory attempt, no resume/retry; return bounded journal metadata."""
    journal.create()
    owned: tuple[Owned, ...] = ()
    failure = None
    preflight_done = False
    try:
        for phase in PHASES[:6]:
            if clock() >= deadline:
                raise TimeoutError("overall deadline")
            journal.record(phase, intent=phase)
            value = getattr(ops, phase)()
            if phase in ("enroll_disabled", "enable_scheduler", "one_bridge_claim"):
                if not isinstance(value, tuple) or not all(isinstance(x, Owned) for x in value):
                    raise ValueError("missing exact resource identities")
                if any(x in owned for x in value) or len(set(value)) != len(value):
                    raise ValueError("duplicate resource identity")
                owned += value
            journal.record(phase, intent=None, status="pending", owned=owned)
            if phase == "preflight":
                preflight_done = True
    except Exception as exc:
        failure = type(exc).__name__
        # If an effect fails after intent, identities may be unknown: no guessed cleanup.
        pending = journal.state["intent"]
        if pending in ("enroll_disabled", "enable_scheduler", "one_bridge_claim"):
            journal.record("blocked", status="blocked", unresolved=pending)
    try:
        journal.record("reconcile", intent="reconcile")
        result = ops.reconcile()
        if result not in {"review-ready", "blocked", "unknown"}:
            raise ValueError("untrusted reconciliation result")
        journal.record("reconcile", intent=None, status=result)
    except Exception as exc:
        failure = failure or type(exc).__name__
        result = "unknown"
    # Reconciliation is read-only; it never clears an unresolved effect.
    uncertain = journal.state["unresolved_effect"] is not None
    try:
        if uncertain:
            raise ValueError("effect intent unresolved")
        if not preflight_done:
            raise ValueError("no preflight baseline; cleanup cannot be verified")
        journal.record("cleanup", intent="cleanup")
        if ops.inspect_owned(owned) is not True:
            raise ValueError("owned resource identity not verified")
        removed = ops.cleanup(owned)
        if not isinstance(removed, tuple) or removed != owned:
            raise ValueError("exact-ID cleanup incomplete")
        if ops.cleanup_readback(owned) is not True:
            raise ValueError("post-cleanup baseline unverified")
        journal.record("cleanup", intent=None, cleanup=True, owned=())
    except Exception as exc:
        failure = failure or type(exc).__name__
        journal.record("blocked", status="blocked",
                       unresolved="cleanup" if journal.state["intent"] == "cleanup" else None)
    if journal.state["cleanup_verified"]:
        try:
            if clock() >= deadline:
                raise TimeoutError("overall deadline")
            journal.record("report", intent="report")
            summary = {"attempt": journal.attempt, "result": result,
                       "cleanup_verified": True, "failure": failure}
            receipt = ops.report(summary)
            if not isinstance(receipt, str) or not ID.fullmatch(receipt):
                raise ValueError("invalid report receipt")
            if ops.report_readback(receipt, summary) is not True:
                raise ValueError("report readback mismatch")
            journal.record("report", intent=None, receipt=receipt,
                           status="review-ready" if result == "review-ready" and not failure else "blocked")
        except Exception:
            # Ambiguous publication intent remains for read-only reconciliation.
            journal.record("blocked", status="blocked",
                           unresolved="report" if journal.state["intent"] == "report" else None)
    return dict(journal.state)


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", action="store_true",
                        help="read-only repository manifest verification; never GO")
    args = parser.parse_args()
    if not args.review:
        raise SystemExit("NO-GO: protected signer, isolated worker proof and host backend not provisioned")
    from verify_review_manifest import verify
    root = Path(__file__).resolve().parents[2]
    count = verify(root, Path(__file__).with_name("review_manifest.json"))
    print(f"REVIEW ONLY: {count} pinned inputs verified; production backend unavailable, no GO")


if __name__ == "__main__":
    main()
