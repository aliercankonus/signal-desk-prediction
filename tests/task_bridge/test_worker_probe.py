"""Offline verified worker probe; no credential or provider requests."""
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('worker_probe', ROOT / 'ops/github_inbox/worker_probe.py')
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def test_probe_uses_worker_adapter_gets_and_git_without_secrets():
    calls = []
    class Adapter:
        def request(self, method, path):
            calls.append((method, path))
            if path == '/user':
                return {'login': 'review-user'}
            if '/check-runs' in path:
                return {'total_count': 1, 'check_runs': [{'head_sha': 'e84021a786004456a12de9e25eae50d191da6cf1', 'status': 'completed', 'conclusion': 'success'}]}
            if path.endswith('/pulls?state=all&head=aliercankonus:issue43-one-shot-review-note&per_page=2'):
                return []
            if path.endswith('/git/ref/heads/main'):
                return {'ref': 'refs/heads/main', 'object': {'sha': 'a' * 40, 'type': 'commit'}}
            return {'number': int(path.rsplit('/', 1)[1]), 'state': 'open', 'body': 'frozen'}
    def git(*args):
        calls.append(('git', args))
        return '' if args[-1] == 'refs/heads/issue43-one-shot-review-note' else 'head-ref'
    status = module.probe(Adapter(), git, 'aliercankonus/signal-desk-prediction', 43)
    assert status == {'authenticated': True, 'task_open': True, 'git_read': True}
    assert calls == [('GET', '/user'),
        ('GET', '/repos/aliercankonus/signal-desk-prediction/issues/43'),
        ('GET', '/repos/aliercankonus/signal-desk-prediction/issues/41'),
        ('GET', '/repos/aliercankonus/signal-desk-prediction/issues/45'),
        ('GET', '/repos/aliercankonus/signal-desk-prediction/git/ref/heads/main'),
        ('GET', '/repos/aliercankonus/signal-desk-prediction/commits/e84021a786004456a12de9e25eae50d191da6cf1/check-runs?per_page=100'),
        ('GET', '/repos/aliercankonus/signal-desk-prediction/pulls?state=all&head=aliercankonus:issue43-one-shot-review-note&per_page=2'),
        ('git', ('ls-remote', 'origin', 'HEAD')),
        ('git', ('ls-remote', 'origin', 'refs/heads/issue43-one-shot-review-note'))]


def test_probe_rejects_existing_task_branch_before_effect():
    class Adapter:
        def request(self, method, path):
            if path == '/user': return {'login': 'worker'}
            if path.endswith('/git/ref/heads/main'):
                return {'ref': 'refs/heads/main', 'object': {'type': 'commit'}}
            if '/check-runs?' in path: return {'total_count': 0, 'check_runs': []}
            if '/pulls?' in path: return []
            return {'number': int(path.rsplit('/', 1)[1]), 'state': 'open'}
    def git(*args):
        return 'unexpected-existing-branch' if args[-1].startswith('refs/heads/') else 'head'
    import pytest
    with pytest.raises(ValueError, match='branch/PR/Checks'):
        module.probe(Adapter(), git, 'aliercankonus/signal-desk-prediction', 43)
