"""Offline checks for the worker's read-only, post-Bridge remote predicate."""
import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('bridge_readback', ROOT / 'ops/bridge_one_shot/bridge_readback.py')
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def row():
    head = 'a' * 40
    url = 'https://github.com/aliercankonus/signal-desk-prediction/pull/123'
    return {'status': 'blocked', 'head': head, 'pr_url': url, 'base': 'e84021a786004456a12de9e25eae50d191da6cf1',
            'run_id': 'b' * 32, 'ci': 'pending', 'result_mismatch': [], 'publication_consistent': True,
            'pr_creation': {'stage': 'verified', 'expected_head': head, 'number': 123, 'url': url},
            'observed_pr': {'head': head, 'url': url, 'ci': 'pending', 'target_tip': 'c' * 40}}


def test_verified_remote_readback_uses_full_bridge_predicate():
    assert module.summarize(row()) == {'verified': True, 'head': 'a' * 40,
        'pr_url': 'https://github.com/aliercankonus/signal-desk-prediction/pull/123',
        'observed_ci': 'pending', 'run_id': 'b' * 32}


def test_remote_draft_missing_issue_link_or_receipt_is_not_success():
    drift = row()
    drift['result_mismatch'] = ['draft PR verification failed']
    assert module.summarize(drift)['verified'] is False
    missing = row()
    missing['pr_creation'] = None
    assert module.summarize(missing)['verified'] is False


def test_remote_publication_uncertainty_is_not_success():
    drift = row()
    drift['publication_consistent'] = False
    assert module.summarize(drift)['verified'] is False
    drift = row()
    drift['publication_inspection_unavailable'] = True
    assert module.summarize(drift)['verified'] is False
