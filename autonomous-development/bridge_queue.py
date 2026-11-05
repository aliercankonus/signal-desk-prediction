"""Opt-in, inert queue-to-Task-Bridge adapter. No watcher or CLI activation."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

from signal_desk.task_bridge.bridge import Bridge, load_authorization, verified_pr_receipt
from signal_desk.task_bridge.context import load_execution_context
from signal_desk.task_bridge.adapters import GitHubREST, HermesAgent
from queue_store import TaskStore


def _revision(source: Path) -> str:
    result = subprocess.run(['git', '-C', str(source), 'rev-parse', 'HEAD'],
                            capture_output=True, text=True, check=True, timeout=10)
    root = subprocess.run(['git', '-C', str(source), 'rev-parse', '--show-toplevel'],
                          capture_output=True, text=True, check=True, timeout=10)
    if Path(root.stdout.strip()).resolve(strict=True) != source:
        raise ValueError('runner source must be the Git checkout root')
    status = subprocess.run(['git', '-C', str(source), 'status', '--porcelain=v1',
                             '-z', '--untracked-files=all'],
                            capture_output=True, check=True, timeout=10)
    if status.stdout:
        raise ValueError('reviewed runner checkout must be clean')
    return result.stdout.strip()


def _context_digest(context) -> str:
    canonical = json.dumps(asdict(context), sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _reviewed_runtime(entry: dict) -> None:
    """Check on-disk runner provenance; trusted interpreter is a prerequisite."""
    source = Path(entry['repo'])
    if _revision(source) != entry['runner_commit']:
        raise ValueError('reviewed runtime checkout changed')
    modules = tuple((name, module) for name, module in sys.modules.items()
                    if name in ('bridge_queue', 'queue_store', 'signal_desk') or
                    name.startswith('signal_desk.task_bridge'))
    for name, module in modules:
        cached = getattr(module, '__cached__', None)
        if cached and Path(cached).exists():
            raise ValueError('loaded runtime bytecode cache is not reviewed')
        if getattr(module, '__file__', None) is None and name != 'signal_desk.task_bridge':
            raise ValueError('loaded runtime module has no source path')
    for name, module in modules:
        loaded = getattr(module, '__file__', None)
        if loaded is None:  # The known namespace package.
            continue
        if name in ('bridge_queue', 'queue_store'):
            relative = Path('autonomous-development') / (name + '.py')
        else:
            stem = Path('src').joinpath(*name.split('.'))
            relative = stem / '__init__.py' if Path(loaded).name == '__init__.py' else stem.with_suffix('.py')
        expected = source / relative
        if Path(loaded).resolve(strict=True) != expected:
            raise ValueError('loaded runtime module differs from reviewed checkout')
        committed = subprocess.run(['git', '-C', str(source), 'show',
                                    f'{entry["runner_commit"]}:{relative.as_posix()}'],
                                   capture_output=True, check=True, timeout=10).stdout
        if expected.read_bytes() != committed:
            raise ValueError('loaded runtime source differs from reviewed commit')


class BridgeQueue:
    """Queue reviewed task references; never enqueue issue prose or credentials."""

    def __init__(self, store: TaskStore):
        self.store = store

    def enqueue(self, source: Path, authorization: Path, context: Path, *, runner_commit: str) -> dict:
        self.store._check()
        source = Path(source).resolve(strict=True)
        authorization = Path(authorization)
        context = Path(context)
        if not isinstance(runner_commit, str) or not re.fullmatch(r'[0-9a-f]{40}', runner_commit):
            raise ValueError('reviewed runner commit required')
        if _revision(source) != runner_commit:
            raise ValueError('installed runner revision differs from reviewed commit')
        policy = load_authorization(authorization)
        auth_location = authorization.resolve(strict=True)
        queue_root = self.store.root.resolve()
        if queue_root == source or source in queue_root.parents:
            raise ValueError('bridge queue must be outside the runner checkout')
        if (auth_location == source or source in auth_location.parents or
                auth_location == queue_root or queue_root in auth_location.parents):
            raise ValueError('authorization must be outside the source and queue state')
        execution = load_execution_context(context, source, self.store.root)
        if execution.runner_commit != runner_commit:
            raise ValueError('private context does not pin the reviewed runner')
        task_id = uuid.uuid4().hex
        with self.store.lock() as acquired:
            if not acquired:
                raise BlockingIOError('queue consumer busy')
            folder = self.store.create_entry_directory(task_id)
            entry = {'id': task_id, 'kind': 'bridge', 'repo': str(source),
                     'authorization_path': str(auth_location),
                     'context_path': str(context.resolve(strict=True)),
                     'authorization_identity': policy.identity,
                     'context_digest': _context_digest(execution),
                     'runner_commit': runner_commit, 'bridge_run_id': uuid.uuid4().hex,
                     'bridge_state': str(folder / 'bridge'), 'created_ns': time.time_ns(),
                     'status': 'queued', 'invocations': 0, 'ci': None, 'pr_url': None,
                     'failure_code': None, 'related': None, 'checkpoint': None}
            self.store.save(entry)
            return entry

    def _reviewed_policy(self, entry: dict):
        task_id = entry['id']
        if (entry.get('kind') != 'bridge' or not re.fullmatch(r'[0-9a-f]{32}', task_id) or
                entry.get('bridge_state') != str(self.store.root / task_id / 'bridge') or
                not isinstance(entry.get('bridge_run_id'), str) or
                not re.fullmatch(r'[0-9a-f]{32}', entry['bridge_run_id']) or
                entry.get('invocations') != 0):
            raise ValueError('queue mapping invalid')
        source = Path(entry['repo']).resolve(strict=True)
        if str(source) != entry['repo'] or _revision(source) != entry['runner_commit']:
            raise ValueError('reviewed runner revision changed')
        authorization = Path(entry['authorization_path']).resolve(strict=True)
        context_path = Path(entry['context_path']).resolve(strict=True)
        queue_root = self.store.root.resolve(strict=True)
        if (str(authorization) != entry['authorization_path'] or
                str(context_path) != entry['context_path'] or
                any(path == ancestor or ancestor in path.parents
                    for path in (authorization, context_path)
                    for ancestor in (source, queue_root))):
            raise ValueError('authority and context must remain outside runner and queue')
        policy = load_authorization(authorization)
        if policy.identity != entry['authorization_identity']:
            raise ValueError('task authorization changed')
        context = load_execution_context(context_path, source, queue_root)
        if (context.runner_commit != entry['runner_commit'] or
                _context_digest(context) != entry['context_digest']):
            raise ValueError('private interpreter context changed')
        state = Path(entry['bridge_state'])
        if state.exists() or state.is_symlink():
            raise ValueError('existing Bridge state requires manual review')
        return policy

    @staticmethod
    def production_bridge(entry: dict, policy):
        """Explicit caller only; never started by the legacy Worker CLI or observer."""
        state = Path(entry['bridge_state'])
        source = Path(entry['repo'])
        _reviewed_runtime(entry)
        return Bridge(state, policy, GitHubREST(policy),
                      HermesAgent(source, state, policy, context_path=entry['context_path']),
                      auth_path=entry['authorization_path'], run_id=entry['bridge_run_id'])

    def dispatch_one(self, bridge_factory) -> dict:
        """One approved queue entry, one Bridge.once; all ambiguous states stop."""
        with self.store.lock() as acquired:
            if not acquired:
                return {'status': 'blocked', 'reason': 'queue consumer busy'}
            try:
                tasks = self.store.all_tasks()
            except (OSError, ValueError, KeyError, TypeError):
                return {'status': 'blocked', 'reason': 'queue state incomplete or invalid'}
            if any(t['status'] == 'running' for t in tasks):
                return {'status': 'blocked', 'reason': 'ambiguous running entry'}
            held = next((t for t in tasks if t.get('kind') == 'bridge' and
                         t['status'] in ('blocked', 'review-ready')), None)
            if held:
                return {'status': held['status'], 'id': held['id'],
                        'ci': held.get('ci')}
            entry = next((t for t in tasks if t.get('kind') == 'bridge' and
                          t['status'] == 'queued'), None)
            if entry is None:
                return {'status': 'empty'}
            try:
                policy = self._reviewed_policy(entry)
            except (OSError, ValueError, KeyError, subprocess.SubprocessError):
                entry.update(status='blocked', failure_code='preflight')
                self.store.save(entry)
                return {'status': 'blocked', 'id': entry['id']}
            entry.update(status='running', invocations=1, started_ns=time.time_ns())
            self.store.save(entry)  # Durable mapping before the factory or Bridge.once.
            try:
                bridge = bridge_factory(entry, policy)
                result = bridge.once()
                if not isinstance(result, dict):
                    raise ValueError('Bridge result invalid')
                if result.get('status') != 'review-ready':
                    if (result.get('run_id') not in (None, entry['bridge_run_id']) or
                            result.get('base') not in (None, policy.base)):
                        raise ValueError('blocked Bridge identity mismatch')
                    bounded = {'status': 'blocked', 'run_id': entry['bridge_run_id']}
                    for field, pattern in (('head', r'[0-9a-f]{40}'),
                                           ('pr_url', r'https://github\.com/aliercankonus/signal-desk-prediction/pull/[1-9][0-9]*')):
                        value = result.get(field)
                        if value is not None:
                            if not isinstance(value, str) or not re.fullmatch(pattern, value):
                                raise ValueError('blocked Bridge result invalid')
                            bounded[field] = value
                    ci = result.get('ci')
                    if ci is not None:
                        if ci not in ('success', 'failure', 'pending', 'unknown'):
                            raise ValueError('blocked Bridge CI invalid')
                        bounded['ci'] = ci
                    if result.get('base') is not None:
                        bounded['base'] = policy.base
                    receipt_fn = getattr(bridge, '_pr_creation', None)
                    receipt = receipt_fn() if receipt_fn else None
                    if receipt is not None:
                        if (not isinstance(receipt, dict) or set(receipt) !=
                                {'stage', 'expected_head', 'number', 'url'} or
                                receipt['stage'] not in ('intent', 'responded', 'verified', 'reused') or
                                not isinstance(receipt['expected_head'], str) or
                                not re.fullmatch(r'[0-9a-f]{40}', receipt['expected_head']) or
                                (bounded.get('head') is not None and
                                 receipt['expected_head'] != bounded['head']) or
                                (receipt['number'] is not None and
                                 (type(receipt['number']) is not int or receipt['number'] < 1)) or
                                (receipt['url'] is not None and
                                 (type(receipt['number']) is not int or
                                  receipt['url'] != f'https://github.com/aliercankonus/signal-desk-prediction/pull/{receipt["number"]}'))):
                            raise ValueError('blocked Bridge receipt invalid')
                        entry['receipt'] = receipt
                    entry.update(status='blocked', ci=ci, pr_url=bounded.get('pr_url'),
                                 failure_code='bridge',
                                 bridge_result=bounded)
                else:
                    if (load_authorization(entry['authorization_path']).identity !=
                            entry['authorization_identity']):
                        raise ValueError('authorization changed during Bridge run')
                    checked_context = load_execution_context(
                        entry['context_path'], Path(entry['repo']), self.store.root)
                    if (_context_digest(checked_context) != entry['context_digest'] or
                            _revision(Path(entry['repo'])) != entry['runner_commit']):
                        raise ValueError('reviewed context or runner changed during Bridge run')
                    head, url, ci = result.get('head'), result.get('pr_url'), result.get('ci')
                    receipt = bridge._pr_creation()
                    if (result.get('run_id') != entry['bridge_run_id'] or
                            result.get('base') != policy.base or
                            not isinstance(head, str) or not re.fullmatch(r'[0-9a-f]{40}', head) or
                            not isinstance(url, str) or
                            not verified_pr_receipt(receipt, head, url) or
                            ci not in ('success', 'failure', 'pending', 'unknown')):
                        raise ValueError('Bridge result or PR receipt invalid')
                    entry.update(status='review-ready', ci=ci, pr_url=url,
                                 bridge_result={'status': 'review-ready', 'run_id': entry['bridge_run_id'],
                                                'base': policy.base, 'head': head, 'pr_url': url, 'ci': ci},
                                 receipt=receipt)
            except Exception:
                # Never store raw exceptions, outputs or issue prose. Preserve Bridge state.
                entry.update(status='blocked', failure_code='ambiguous')
            entry['finished_ns'] = time.time_ns()
            self.store.save(entry)
            return {'status': entry['status'], 'id': entry['id'], 'ci': entry.get('ci')}
