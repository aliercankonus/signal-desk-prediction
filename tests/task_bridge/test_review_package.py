"""Offline checks for immutable #41 inputs across later follow-up edits."""
import importlib.util
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / 'ops/bridge_one_shot/verify_review_manifest.py'
SPEC = importlib.util.spec_from_file_location('review_manifest_verifier', MODULE)
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)
MANIFEST = ROOT / 'ops/bridge_one_shot/review_manifest.json'


def _snapshot(tmp_path):
    """Use pinned old blobs, not edited follow-up bytes, for frozen input checks."""
    root = tmp_path / 'snapshot'
    manifest = json.loads(MANIFEST.read_text())
    for name in (*manifest['frozen_source_sha256'], *manifest['candidate_files_sha256']):
        destination = root / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, destination)
    name = 'ops/bridge_one_shot/worker_firewall.sh'
    # The CI image copies source without .git. Remove only this PR's two
    # additions; the pinned digest then proves the reconstructed old blob.
    updated = (root / name).read_bytes()
    old = updated.replace(b'PATH=/usr/sbin:/sbin:/usr/bin:/bin\nexport PATH\n', b'', 1).replace(
        b'for tool in iptables ip docker python3 wc; do\n'
        b'  command -v "$tool" >/dev/null || { echo "NO-GO: required host tool unavailable: $tool" >&2; exit 2; }\n'
        b'done\n', b'', 1)
    assert old != updated and hashlib.sha256(old).hexdigest() == manifest['frozen_source_sha256'][name]
    (root / name).write_bytes(old)
    return root


def _inert_git(monkeypatch, root):
    def git_show(argv, **kwargs):
        assert argv[:4] == ['git', '-C', str(root), 'show']
        revision, path = argv[4].split(':', 1)
        assert revision == 'e84021a786004456a12de9e25eae50d191da6cf1'
        return subprocess.CompletedProcess(argv, 0, stdout=(root / path).read_bytes())
    monkeypatch.setattr(verifier.subprocess, 'run', git_show)


def _changed_manifest(tmp_path, change):
    data = json.loads(MANIFEST.read_text(encoding='utf-8'))
    change(data)
    path = tmp_path / 'manifest.json'
    path.write_text(json.dumps(data), encoding='utf-8')
    return path


def test_frozen_inputs_match_candidate_with_no_verifier_network(monkeypatch, tmp_path):
    root = _snapshot(tmp_path)
    _inert_git(monkeypatch, root)
    assert verifier.verify(root, MANIFEST) == 19
    manifest = json.loads(MANIFEST.read_text())
    candidate = (ROOT / 'ops/bridge_one_shot/bridge_once_candidate.py').read_text()
    compose = (ROOT / 'ops/bridge_one_shot/compose.candidate.yml').read_text()
    assert manifest['candidate_runner'] in candidate
    assert manifest['existing_host_runner'] not in candidate
    assert 'bridge_once_candidate.py' in compose
    assert '${BRIDGE_ONCE_APPROVED:-no}' in compose
    assert 'restart: "no"' in compose


def test_reject_changed_runner_before_git(monkeypatch, tmp_path):
    monkeypatch.setattr(verifier.subprocess, 'run', lambda *_a, **_k: pytest.fail('git invoked'))
    path = _changed_manifest(tmp_path, lambda d: d.update(candidate_runner='0' * 40))
    with pytest.raises(ValueError, match='runner/start transition'):
        verifier.verify(ROOT, path)


def test_reject_changed_source_or_candidate_digest(monkeypatch, tmp_path):
    root = _snapshot(tmp_path)
    _inert_git(monkeypatch, root)
    path = _changed_manifest(tmp_path, lambda d: d['frozen_source_sha256'].update({'ops/github_inbox/inboxctl.py': '0' * 64}))
    with pytest.raises(ValueError, match='working source differs'):
        verifier.verify(root, path)
    path = _changed_manifest(tmp_path, lambda d: d['candidate_files_sha256'].update({'ops/bridge_one_shot/compose.candidate.yml': '0' * 64}))
    with pytest.raises(ValueError, match='candidate file changed'):
        verifier.verify(root, path)


def test_reject_path_escape_and_changed_issue_body(monkeypatch, tmp_path):
    root = _snapshot(tmp_path)
    _inert_git(monkeypatch, root)
    path = _changed_manifest(tmp_path, lambda d: d['frozen_source_sha256'].update({'../private': '0' * 64}))
    with pytest.raises(ValueError, match='unsafe source path'):
        verifier.verify(root, path)
    wrong_body = tmp_path / 'body.txt'
    wrong_body.write_text('edited issue body\n', encoding='utf-8')
    with pytest.raises(ValueError, match='frozen task issue body differs'):
        verifier.verify(root, MANIFEST, wrong_body)
