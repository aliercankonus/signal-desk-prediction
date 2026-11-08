"""Static checks for the review-only inbox enrollment/mount proposal."""

import json
from pathlib import Path
import re


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
