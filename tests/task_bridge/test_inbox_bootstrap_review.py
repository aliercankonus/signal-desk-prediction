"""Static checks for the review-only inbox enrollment/mount proposal."""

import json
from pathlib import Path
import re

import pytest


ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "ops/github_inbox/BOOTSTRAP_REVIEW.md"
COMPOSE = ROOT / "ops/github_inbox/compose.inbox.candidate.yml"


def test_enrollment_has_exact_reviewed_scope_and_remains_disabled():
    text = DOC.read_text(encoding="utf-8")
    example = json.loads(re.search(r"```json\n([^\n]+)\n```", text).group(1))
    assert set(example) == {"repo", "issues", "task_issue", "runner", "runner_commit",
                            "queue", "authorization", "context", "public_key",
                            "public_key_sha256", "interval_seconds"}
    assert example["issues"] == [41, 45] and example["task_issue"] == 43
    assert example["runner_commit"] == "e84021a786004456a12de9e25eae50d191da6cf1"
    assert example["runner"] == "/workspace/runner"
    assert example["queue"] == "/state/queue"
    assert "--state /state/github-inbox" in text
    assert "--start '<actual-enrollment-UTC-YYYY-MM-DDTHH:MM:SSZ>'" in text
    assert "# STOP: state is disabled" in text
    assert "inboxctl.py \\\n  enroll" in text and "inboxctl.py \\\n  doctor" in text
    assert "inboxctl.py \\\n  enable" not in text and "inboxctl.py \\\n  tick" not in text


def test_manifest_candidate_branch_is_accepted_by_pinned_policy():
    import hashlib
    from signal_desk.task_bridge.bridge import Policy
    manifest = json.loads((ROOT / "ops/bridge_one_shot/review_manifest.json").read_text())
    source = (ROOT / "src/signal_desk/task_bridge/bridge.py").read_bytes()
    assert hashlib.sha256(source).hexdigest() == manifest["frozen_source_sha256"]["src/signal_desk/task_bridge/bridge.py"]
    policy = Policy(repo=manifest["repository"], issue=manifest["task_issue"],
                    body_digest=manifest["task_body_sha256"],
                    base=manifest["candidate_task_start"],
                    branch=manifest["candidate_task_branch"])
    assert policy.branch == "issue43-one-shot-review-note"


def test_frozen_policy_loads_through_private_enrollment_and_context(monkeypatch):
    import hashlib
    import sys
    import tempfile
    from signal_desk.task_bridge.bridge import Policy
    from signal_desk.task_bridge.context import load_execution_context
    worker = ROOT / "autonomous-development"
    sys.path.insert(0, str(worker))
    from github_inbox import load_enrollment
    import github_inbox

    manifest = json.loads((ROOT / "ops/bridge_one_shot/review_manifest.json").read_text())
    pin = manifest["candidate_runner"]
    with tempfile.TemporaryDirectory(dir=Path.home(), prefix="sd-enrollment-test-") as temporary:
        base = Path(temporary)
        runner = base / "runner"
        runner.mkdir(mode=0o700)
        state = base / "state"
        state.mkdir(mode=0o700)
        queue = state / "queue"
        queue.mkdir(mode=0o700)
        auth = base / "auth"
        auth.mkdir(mode=0o700)
        context_dir = base / "context"
        context_dir.mkdir(mode=0o700)
        key_dir = base / "key"
        key_dir.mkdir(mode=0o700)
        key = key_dir / "manager-public.pem"
        key.write_bytes(b"test-only public verifier")
        key.chmod(0o600)
        policy = Policy(repo=manifest["repository"], issue=43,
                        body_digest=manifest["task_body_sha256"],
                        base=manifest["candidate_task_start"],
                        branch=manifest["candidate_task_branch"])
        authorization = auth / "authorization.json"
        authorization.write_text(json.dumps(vars(policy)))
        authorization.chmod(0o600)
        context = context_dir / "context.json"
        context.write_text(json.dumps({"test_python": "/approved/venv/bin/python",
            "requirements_sha256": "a" * 64, "runner_commit": pin,
            "python_version": "3.14.9", "pytest_version": "8.3.3"}))
        context.chmod(0o600)
        enrollment = key_dir / "enrollment.json"
        enrollment.write_text(json.dumps({"repo": manifest["repository"], "issues": [41, 45],
            "task_issue": 43, "runner": str(runner), "runner_commit": pin,
            "queue": str(queue), "authorization": str(authorization),
            "context": str(context), "public_key": str(key),
            "public_key_sha256": hashlib.sha256(key.read_bytes()).hexdigest(),
            "interval_seconds": 300}))
        enrollment.chmod(0o600)
        monkeypatch.setattr(github_inbox, "_revision", lambda path: pin)
        config, loaded, public = load_enrollment(enrollment)
        assert config["runner_commit"] == pin and loaded == policy
        assert public == key.read_bytes()
        assert load_execution_context(context, runner, queue).runner_commit == pin
        context.write_text(context.read_text().replace(pin, "0" * 40))
        with pytest.raises(ValueError, match="execution context changed"):
            load_enrollment(enrollment)


def test_candidate_compose_only_adds_worker_inbox_mounts_no_signer_or_activation():
    text = COMPOSE.read_text(encoding="utf-8")
    worker, proxy = text.split("\n  connect-proxy:\n", 1)
    assert "BRIDGE_STATE_PARENT_HOST" in worker and "target: /state" in worker
    assert "BRIDGE_INBOX_CONFIG_HOST" in worker and "target: /private/inbox" in worker
    assert "read_only: true" in worker
    assert "${BRIDGE_ONCE_APPROVED:-no}" in worker
    assert "BRIDGE_INBOX_CONFIG_HOST" not in proxy and "BRIDGE_STATE_PARENT_HOST" not in proxy
    assert "signer-private" not in text and "manager-private" not in text
    assert "restart: \"no\"" in text
