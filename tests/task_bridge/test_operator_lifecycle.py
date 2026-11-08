"""Provider-free failure matrix for the dormant one-entry phase journal."""

import importlib.util
import json
from pathlib import Path
import tempfile

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "operator_lifecycle", ROOT / "ops/bridge_one_shot/operator_lifecycle.py")
assert SPEC is not None and SPEC.loader is not None
import sys
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class FakeOps:
    def __init__(self, fail=None):
        self.fail = fail
        self.calls = []
        self.resources = (
            module.Owned("enrollment", "inbox-1", "attempt1"),
            module.Owned("scheduler", "timer-1", "attempt1"),
            module.Owned("worker", "container-1", "attempt1"),
        )
        self.reconciled = "review-ready"

    def _call(self, name, value=None):
        self.calls.append(name)
        if self.fail == name:
            raise RuntimeError("private diagnostic must not leak")
        return value

    def preflight(self): return self._call("preflight")
    def start_isolation(self): return self._call("start_isolation", ())
    def login(self): return self._call("login")
    def github_reads(self): return self._call("github_reads")
    def enroll_disabled(self): return self._call("enroll_disabled", (self.resources[0],))
    def enable_inbox(self): return self._call("enable_inbox", (self.resources[1],))
    def one_bridge_claim(self): return self._call("one_bridge_claim", (self.resources[2],))
    def reconcile(self): return self._call("reconcile", self.reconciled)
    def inspect_owned(self, resources):
        assert resources == self.resources
        return self._call("inspect_owned", True)
    def cleanup(self, resources):
        assert resources == self.resources
        return self._call("cleanup", resources)
    def cleanup_readback(self, resources):
        assert resources == self.resources
        return self._call("cleanup_readback", True)
    def report(self, sanitized):
        assert sanitized["cleanup_verified"] is True
        assert "private diagnostic" not in str(sanitized)
        return self._call("report", "comment-123")
    def report_readback(self, receipt, sanitized):
        assert receipt == "comment-123" and sanitized["cleanup_verified"]
        return self._call("report_readback", True)


def _attempt():
    # The real Journal rejects sticky/world-writable ancestors including /tmp.
    return tempfile.TemporaryDirectory(dir=Path.home(), prefix="sd-issue41-test-")


def test_isolation_startup_failure_is_intent_fenced_and_never_cleans_unknown_ids():
    with _attempt() as root:
        journal = module.Journal(Path(root) / "attempt1", "attempt1")
        ops = FakeOps(fail="start_isolation")
        state = module.run_once(journal, ops, deadline=100, clock=lambda: 0)
        assert state["unresolved_effect"] == "start_isolation"
        assert "start_isolation" in ops.calls
        assert "login" not in ops.calls and "cleanup" not in ops.calls and "report" not in ops.calls


def test_expired_total_budget_does_not_begin_unbounded_cleanup():
    with _attempt() as root:
        journal = module.Journal(Path(root) / "attempt1", "attempt1")
        now = [0]
        ops = FakeOps()
        def start():
            ops.calls.append("start_isolation")
            now[0] = 101
            return (module.Owned("proxy", "proxy-1", "attempt1"),)
        ops.start_isolation = start
        ops.inspect_owned = lambda resources: True
        ops.cleanup = lambda resources: ops.calls.append("cleanup") or resources
        ops.cleanup_readback = lambda resources: True
        state = module.run_once(journal, ops, deadline=100, clock=lambda: now[0])
        assert state["status"] == "blocked"
        assert not state["cleanup_verified"]
        assert "cleanup" not in ops.calls and "report" not in ops.calls
        assert state["owned"][0]["ident"] == "proxy-1"


def test_one_success_and_durable_report_after_exact_cleanup():
    with _attempt() as root:
        journal = module.Journal(Path(root) / "attempt1", "attempt1")
        ops = FakeOps()
        state = module.run_once(journal, ops, deadline=100, clock=lambda: 0)
        assert state["status"] == "review-ready"
        assert state["cleanup_verified"] and state["report_receipt"] == "comment-123"
        assert ops.calls.index("cleanup") < ops.calls.index("report")
        assert json.loads(journal.file.read_text()) == state
        assert journal.file.stat().st_mode & 0o077 == 0
        with pytest.raises(FileExistsError):
            module.run_once(module.Journal(journal.directory, "attempt1"), FakeOps(),
                            deadline=100, clock=lambda: 0)


@pytest.mark.parametrize("stage", ("enroll_disabled", "enable_inbox", "one_bridge_claim"))
def test_post_intent_error_preserves_claim_and_refuses_cleanup_or_report(stage):
    with _attempt() as root:
        journal = module.Journal(Path(root) / "attempt1", "attempt1")
        ops = FakeOps(fail=stage)
        state = module.run_once(journal, ops, deadline=100, clock=lambda: 0)
        assert state["status"] == "blocked" and state["unresolved_effect"] == stage
        assert not state["cleanup_verified"]
        assert "reconcile" in ops.calls
        assert "cleanup" not in ops.calls and "report" not in ops.calls
        assert "private diagnostic" not in journal.file.read_text()


def test_incomplete_exact_id_cleanup_cannot_publish_success():
    with _attempt() as root:
        journal = module.Journal(Path(root) / "attempt1", "attempt1")
        ops = FakeOps()
        ops.cleanup = lambda resources: resources[:-1]
        state = module.run_once(journal, ops, deadline=100, clock=lambda: 0)
        assert state["unresolved_effect"] == "cleanup"
        assert not state["cleanup_verified"] and state["report_receipt"] is None
        assert len(state["owned"]) == 3


@pytest.mark.parametrize("bad", ("inspect_owned", "cleanup_readback"))
def test_cleanup_identity_or_baseline_mismatch_blocks_report(bad):
    with _attempt() as root:
        journal = module.Journal(Path(root) / "attempt1", "attempt1")
        ops = FakeOps()
        setattr(ops, bad, lambda resources: False)
        state = module.run_once(journal, ops, deadline=100, clock=lambda: 0)
        assert state["unresolved_effect"] == "cleanup"
        assert not state["cleanup_verified"] and "report" not in ops.calls
        if bad == "inspect_owned":
            assert "cleanup" not in ops.calls


def test_lost_report_response_remains_ambiguous_not_reposted():
    with _attempt() as root:
        journal = module.Journal(Path(root) / "attempt1", "attempt1")
        ops = FakeOps(fail="report")
        state = module.run_once(journal, ops, deadline=100, clock=lambda: 0)
        assert state["cleanup_verified"] and state["unresolved_effect"] == "report"
        assert state["report_receipt"] is None and ops.calls.count("report") == 1


def test_reject_world_writable_ancestor_before_creating_attempt():
    import uuid
    candidate = Path("/tmp") / ("sd-issue41-forbidden-" + uuid.uuid4().hex)
    journal = module.Journal(candidate, "forbidden")
    with pytest.raises(PermissionError, match="ancestor"):
        journal.create()
    assert not candidate.exists()


def test_reject_foreign_owned_nonwritable_ancestor_before_attempt(monkeypatch):
    import os
    import stat
    from types import SimpleNamespace
    with _attempt() as root:
        parent = Path(root) / "foreign-readonly"
        parent.mkdir(mode=0o755)
        candidate = parent / "attempt1"
        real_lstat = Path.lstat
        def foreign_lstat(path, *args, **kwargs):
            if path == parent:
                return SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_uid=os.getuid() + 1)
            return real_lstat(path, *args, **kwargs)
        monkeypatch.setattr(Path, "lstat", foreign_lstat)
        ops = FakeOps()
        with pytest.raises(PermissionError, match="ancestor"):
            module.run_once(module.Journal(candidate, "attempt1"), ops,
                            deadline=100, clock=lambda: 0)
        assert not candidate.exists() and ops.calls == []


@pytest.mark.parametrize("owner", ("current", "root"))
def test_trusted_nonwritable_ancestor_allows_private_attempt(monkeypatch, owner):
    import os
    import stat
    from types import SimpleNamespace
    with _attempt() as root:
        parent = Path(root) / "trusted-readonly"
        parent.mkdir(mode=0o755)
        candidate = parent / "attempt1"
        actual_lstat = Path.lstat
        def trusted_lstat(path, *args, **kwargs):
            if path == parent:
                return SimpleNamespace(st_mode=stat.S_IFDIR | 0o755,
                                       st_uid=0 if owner == "root" else os.geteuid())
            return actual_lstat(path, *args, **kwargs)
        with monkeypatch.context() as patcher:
            patcher.setattr(Path, "lstat", trusted_lstat)
            journal = module.Journal(candidate, "attempt1")
            journal.create()
        assert journal.directory.is_dir() and journal.directory.stat().st_mode & 0o077 == 0


def test_readback_mismatch_preserves_publication_intent():
    with _attempt() as root:
        journal = module.Journal(Path(root) / "attempt1", "attempt1")
        class BadReadback(FakeOps):
            def report_readback(self, receipt, sanitized):
                self.calls.append("report_readback")
                return False
        ops = BadReadback()
        state = module.run_once(journal, ops, deadline=100, clock=lambda: 0)
        assert state["unresolved_effect"] == "report"
        assert state["cleanup_verified"] and state["report_receipt"] is None
        assert ops.calls.count("report") == 1


def test_deadline_before_preflight_never_claims_cleanup_or_reports():
    with _attempt() as root:
        journal = module.Journal(Path(root) / "attempt1", "attempt1")
        ops = FakeOps()
        state = module.run_once(journal, ops, deadline=0, clock=lambda: 0)
        assert "enroll_disabled" not in ops.calls and "cleanup" not in ops.calls
        assert state["status"] == "blocked" and not state["cleanup_verified"]
        assert state["report_receipt"] is None
