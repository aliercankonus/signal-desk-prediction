"""Offline, provider-free checks for the dormant #41 input manifest."""

import importlib.util
import json
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "ops/bridge_one_shot/verify_review_manifest.py"
SPEC = importlib.util.spec_from_file_location("review_manifest_verifier", MODULE)
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)
MANIFEST = ROOT / "ops/bridge_one_shot/review_manifest.json"


def _inert_git(monkeypatch):
    def git_show(argv, **kwargs):
        assert argv[:4] == ["git", "-C", str(ROOT), "show"]
        revision, path = argv[4].split(":", 1)
        assert revision == "e84021a786004456a12de9e25eae50d191da6cf1"
        return subprocess.CompletedProcess(argv, 0, stdout=(ROOT / path).read_bytes())

    monkeypatch.setattr(verifier.subprocess, "run", git_show)


def _changed_manifest(tmp_path, change):
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    change(data)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_frozen_inputs_match_candidate_with_no_real_git_or_network(monkeypatch):
    _inert_git(monkeypatch)
    assert verifier.verify(ROOT, MANIFEST) == 19
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    candidate = (ROOT / "ops/bridge_one_shot/bridge_once_candidate.py").read_text()
    compose = (ROOT / "ops/bridge_one_shot/compose.candidate.yml").read_text()
    assert manifest["candidate_runner"] in candidate
    assert manifest["existing_host_runner"] not in candidate
    assert "bridge_once_candidate.py" in compose
    assert "${BRIDGE_ONCE_APPROVED:-no}" in compose
    assert "restart: \"no\"" in compose


def test_reject_changed_runner_before_git(monkeypatch, tmp_path):
    monkeypatch.setattr(verifier.subprocess, "run", lambda *_a, **_k: pytest.fail("git invoked"))
    path = _changed_manifest(tmp_path, lambda d: d.update(candidate_runner="0" * 40))
    with pytest.raises(ValueError, match="runner/start transition"):
        verifier.verify(ROOT, path)


def test_reject_changed_source_or_candidate_digest(monkeypatch, tmp_path):
    _inert_git(monkeypatch)
    path = _changed_manifest(tmp_path, lambda d: d["frozen_source_sha256"].update({"ops/github_inbox/inboxctl.py": "0" * 64}))
    with pytest.raises(ValueError, match="working source differs"):
        verifier.verify(ROOT, path)
    path = _changed_manifest(tmp_path, lambda d: d["candidate_files_sha256"].update({"ops/bridge_one_shot/compose.candidate.yml": "0" * 64}))
    with pytest.raises(ValueError, match="candidate file changed"):
        verifier.verify(ROOT, path)


def test_reject_path_escape_and_changed_issue_body(monkeypatch, tmp_path):
    _inert_git(monkeypatch)
    path = _changed_manifest(tmp_path, lambda d: d["frozen_source_sha256"].update({"../private": "0" * 64}))
    with pytest.raises(ValueError, match="unsafe source path"):
        verifier.verify(ROOT, path)
    wrong_body = tmp_path / "body.txt"
    wrong_body.write_text("edited issue body\n", encoding="utf-8")
    with pytest.raises(ValueError, match="frozen task issue body differs"):
        verifier.verify(ROOT, MANIFEST, wrong_body)
