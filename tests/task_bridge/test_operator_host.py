"""Inert command-boundary tests for the dormant host adapter."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('operator_host', ROOT / 'ops/bridge_one_shot/operator_host.py')
assert SPEC and SPEC.loader
host = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = host
SPEC.loader.exec_module(host)


def plan():
    return host.Plan(attempt='attempt1', bundle=Path('/review'), source=Path('/source'),
        merge='5a9c6f5ff4be1f161d817da127ca6799e4a21dfd',
        image='sha256:' + 'a' * 64, uid=10000, gid=10000,
        runner=Path('/runner'), state=Path('/state'), auth=Path('/auth'),
        context=Path('/context'), home=Path('/home'), venv=Path('/venv'),
        inbox=Path('/inbox'), signer_token=Path('/signer/token'),
        signer_key=Path('/signer/key'), signer_public=Path('/signer/public.pem'),
        signer_policy=Path('/signer/scope.json'), signer_state_root=host.SIGNER_STATE_ROOT, overall_seconds=3600,
        journal_parent=Path('/journals'))


class FakeRunner:
    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail
    def __call__(self, argv, *, timeout, env=None, input=None):
        self.calls.append((tuple(argv), timeout))
        if self.fail and self.fail in ' '.join(argv):
            raise TimeoutError('bounded command stopped')
        return ''


def test_shared_root_signer_claims_are_not_scoped_to_an_attempt():
    import dataclasses
    assert plan().signer_state_root == host.SIGNER_STATE_ROOT
    assert plan().signer_state_root != plan().journal_parent / plan().attempt / 'signer'
    with pytest.raises(ValueError, match='unreviewed operator plan'):
        dataclasses.replace(plan(), signer_state_root=Path('/alternate/claims'))


def test_empty_instruction_window_allows_known_resource_cleanup(monkeypatch):
    import dataclasses
    import tempfile
    import time
    import root_signer
    with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
        state = Path(directory)
        (state / 'github-inbox').mkdir(mode=0o700)
        ops = host.HostOperations(dataclasses.replace(plan(), state=state), runner=FakeRunner(),
                                  signer=object(), deadline=time.monotonic() + 30)
        ops.enrollment_inode = str((state / 'github-inbox').stat().st_ino)
        monkeypatch.setattr(root_signer, 'load_scope', lambda path: object())
        monkeypatch.setattr(host, 'check_signer_binding', lambda *args: None)
        assert ops.one_bridge_claim() == ()
        assert ops.claim_status is None


def test_tick_budget_reserves_reconcile_cleanup_and_report(monkeypatch):
    import dataclasses
    import tempfile
    import time
    import root_signer
    with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
        state = Path(directory)
        (state / 'github-inbox').mkdir(mode=0o700)
        ops = host.HostOperations(dataclasses.replace(plan(), state=state), runner=FakeRunner(),
                                  signer=object(), deadline=time.monotonic() + 700)
        ops.enrollment_inode = str((state / 'github-inbox').stat().st_ino)
        monkeypatch.setattr(root_signer, 'load_scope', lambda path: object())
        monkeypatch.setattr(root_signer, 'sign_scan', lambda *a, **k: {'status': 'verified'})
        monkeypatch.setattr(host, 'check_signer_binding', lambda *args: None)
        durations = []
        def inbox(action, *, timeout):
            durations.append(timeout)
            return {'status': 'review-ready'}
        ops._inbox = inbox
        assert ops.one_bridge_claim() == ()
        assert len(durations) == 1 and durations[0] <= 700 - host.CLEANUP_RESERVE
        assert host.CLEANUP_RESERVE >= 400


def test_host_reconcile_ignores_forged_worker_verifier(tmp_path, monkeypatch):
    import dataclasses
    from types import SimpleNamespace
    import root_signer
    from test_bridge_readback import fixture, QUEUE, DIGEST, HEAD, BRANCH
    queue, _, api = fixture(tmp_path)
    cfg = dataclasses.replace(plan(), state=queue.parent,
                              bundle=ROOT / 'ops/bridge_one_shot')
    monkeypatch.setattr(root_signer, 'load_scope', lambda _: SimpleNamespace(
        body_digest=DIGEST, authority_identity='e' * 64))
    ops = host.HostOperations(cfg, runner=FakeRunner(),
                              github=SimpleNamespace(get=lambda path: api[path]))
    claim = {'status': 'review-ready', 'grant_id': 123, 'queue_id': QUEUE,
             'publication_intent': None}
    ops.claim_status = {'status': 'review-ready', 'claim': dict(claim)}
    ops._inbox = lambda action: {'claim': claim}
    ops._worker = lambda *a, **k: (_ for _ in ()).throw(AssertionError('worker code must not be run'))
    assert ops.reconcile() == 'review-ready'
    assert ops.remote_result['observed_ci'] == 'pending'
    # A malicious worker can replace its verifier/output; the root predicate
    # observes the remote branch independently and refuses counterfeit success.
    api[f'/repos/aliercankonus/signal-desk-prediction/git/ref/heads/{BRANCH}']['object']['sha'] = '9' * 40
    ops.remote_result = None
    assert ops.reconcile() == 'blocked'
    assert ops.remote_result is None


def test_oversized_merged_git_blob_is_refused_before_capture():
    calls = []
    def runner(argv, *, timeout, env=None, input=None):
        calls.append(tuple(argv))
        if 'cat-file' in argv and '-s' in argv:
            return '65537\n'
        raise AssertionError('git show must not capture an oversized blob')
    ops = host.HostOperations(plan(), runner=runner)
    with pytest.raises(ValueError, match='blob size'):
        ops.merged_blob('ops/github_inbox/root_signer.py')
    assert len(calls) == 1 and calls[0][-3:-1] == ('cat-file', '-s')


def test_merged_artifact_inventory_is_exact_runtime_dependency_set():
    inventory = json.loads((ROOT / 'ops/bridge_one_shot/operator_artifacts.json').read_text())
    assert inventory['schema'] == 1
    assert inventory['runner_commit'] == host.RUNNER_PIN
    assert len(inventory['files']) == len(set(inventory['files']))
    assert set(inventory['files']) == host.ARTIFACTS
    assert 'ops/bridge_one_shot/bridge_readback.py' in host.ARTIFACTS


def test_worker_owned_private_mount_does_not_have_to_be_root_owned(monkeypatch):
    import os
    import stat
    import tempfile
    from types import SimpleNamespace
    with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
        mount = Path(directory) / 'worker-state'
        mount.mkdir(mode=0o700)
        original = Path.lstat
        def pretend(path, *args, **kwargs):
            if path == mount:
                return SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_uid=10000)
            return original(path, *args, **kwargs)
        monkeypatch.setattr(Path, 'lstat', pretend)
        host.trusted_worker_mount(mount, 10000)
        with pytest.raises(PermissionError):
            host.trusted_worker_mount(mount, 10001)


def test_exact_attempt_start_and_cleanup_with_inert_docker_boundary(tmp_path):
    import dataclasses
    import os
    import tempfile
    with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
        state = Path(directory) / 'state'
        state.mkdir(mode=0o700)
        inbox = state / 'github-inbox'
        inbox.mkdir(mode=0o700)
        (inbox / 'state.json').write_text(json.dumps({'enabled': False}))
        (inbox / 'state.json').chmod(0o600)
        worker, proxy = 'a' * 64, 'b' * 64
        network_ids = {'worker_isolated': 'c' * 64, 'proxy_uplink': 'd' * 64}
        cfg = dataclasses.replace(plan(), state=state, uid=os.geteuid())
        class Platform(FakeRunner):
            def __call__(self, argv, *, timeout, env=None, input=None):
                argv = tuple(argv)
                self.calls.append((argv, timeout))
                text = ' '.join(argv)
                if 'compose' in argv and 'ps' in argv:
                    return worker if argv[-1] == 'inbox-worker' else proxy
                if argv[:3] == ('docker', 'inspect', '--type'):
                    ident = argv[-1]
                    service = 'inbox-worker' if ident == worker else 'connect-proxy'
                    return json.dumps({'Id': ident, 'Image': cfg.image,
                        'Config': {'Labels': {'org.signal-desk.issue41.attempt': cfg.attempt,
                            'com.docker.compose.project': 'signal-desk-bridge-once',
                            'com.docker.compose.service': service}}, 'State': {'Running': True}})
                if argv[:3] == ('docker', 'network', 'ls'):
                    for role in network_ids:
                        if 'label=com.docker.compose.network=' + role in argv:
                            return network_ids[role]
                    return ''
                if argv[:3] == ('docker', 'network', 'inspect'):
                    role = next(k for k, v in network_ids.items() if v == argv[-1])
                    return json.dumps([{'Labels': {'org.signal-desk.issue41.attempt': cfg.attempt},
                        'Id': network_ids[role], 'Containers': {}}])
                if 'network_resources.py' in text:
                    return network_ids[argv[argv.index('--role') + 1]]
                if argv[:2] == ('iptables', '-S'):
                    return ''
                return ''
        platform = Platform()
        ops = host.HostOperations(cfg, runner=platform)
        ops.baseline = ('', '')
        started = ops.start_isolation()
        ops.enrollment_inode = str(inbox.stat().st_ino)
        resources = started + (host.Owned('enrollment', ops.enrollment_inode, cfg.attempt),)
        ops._inbox = lambda action, *args, **kwargs: {'enabled': False}
        assert ops.inspect_owned(resources)
        assert ops.cleanup(resources) == resources
        assert ops.cleanup_readback(resources)
        order = [' '.join(argv) for argv, _ in platform.calls]
        assert any('up -d' in line and 'connect-proxy' in line for line in order)
        assert any('docker stop --time 5 ' + worker in line for line in order)
        assert any('docker stop --time 5 ' + proxy in line for line in order)
        assert any('docker network rm ' + network_ids['worker_isolated'] in line for line in order)


def test_cleanup_after_login_failure_before_enrollment_uses_only_recorded_ids(monkeypatch):
    runner = FakeRunner()
    ops = host.HostOperations(plan(), runner=runner)
    ops.baseline = ('', '')
    ops.worker_id, ops.proxy_id = 'a' * 64, 'b' * 64
    ops.network_ids = {'worker_isolated': 'c' * 64, 'proxy_uplink': 'd' * 64}
    resources = tuple(host.Owned(kind, ident, 'attempt1') for kind, ident in (
        ('network', 'c' * 64), ('network', 'd' * 64), ('proxy', 'b' * 64),
        ('firewall', 'SD_ONCE_IN'), ('worker', 'a' * 64)))
    monkeypatch.setattr(ops, '_container', lambda *a, **k: {})
    monkeypatch.setattr(ops, '_network', lambda *a, **k: None)
    assert ops.inspect_owned(resources)
    assert ops.cleanup(resources) == resources
    assert not any('inboxctl.py' in ' '.join(argv) for argv, _ in runner.calls)


def test_root_scope_must_match_private_worker_authorization_and_public_key():
    import dataclasses
    import hashlib
    import os
    import tempfile
    from root_signer import Scope
    with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
        root = Path(directory)
        auth = root / 'auth'; auth.mkdir(mode=0o700)
        inbox = root / 'inbox'; inbox.mkdir(mode=0o700)
        private_policy = {'repo': 'aliercankonus/signal-desk-prediction', 'issue': 43,
            'body_digest': 'b' * 64, 'base': 'e84021a786004456a12de9e25eae50d191da6cf1',
            'branch': 'issue43-one-shot-review-note'}
        (auth / 'authorization.json').write_text(json.dumps(private_policy))
        (auth / 'authorization.json').chmod(0o600)
        public = b'test-only-public-pem'
        (inbox / 'manager-public.pem').write_bytes(public)
        (inbox / 'manager-public.pem').chmod(0o600)
        root_public = root / 'root-public.pem'
        root_public.write_bytes(public); root_public.chmod(0o600)
        record = {'repo': private_policy['repo'], 'issues': [41, 45], 'task_issue': 43,
            'runner': '/workspace/runner', 'runner_commit': private_policy['base'],
            'queue': '/state/queue', 'authorization': '/private/auth/authorization.json',
            'context': '/private/context/context.json',
            'public_key': '/private/inbox/manager-public.pem',
            'public_key_sha256': hashlib.sha256(public).hexdigest(), 'interval_seconds': 300}
        (inbox / 'enrollment.json').write_text(json.dumps(record))
        (inbox / 'enrollment.json').chmod(0o600)
        identity = hashlib.sha256(json.dumps(private_policy, sort_keys=True,
            separators=(',', ':')).encode()).hexdigest()
        scope = Scope(repo=private_policy['repo'], task_issue=43, body_digest='b' * 64,
            authority_identity=identity, runner_commit=private_policy['base'],
            start='2026-11-08T00:00:00Z', cursors={'41': 1, '45': 2}, app_id=1144995)
        cfg = dataclasses.replace(plan(), auth=auth, inbox=inbox,
                                  signer_public=root_public, uid=os.geteuid())
        host.check_signer_binding(cfg, scope)
        record['public_key_sha256'] = '0' * 64
        (inbox / 'enrollment.json').write_text(json.dumps(record))
        with pytest.raises(ValueError):
            host.check_signer_binding(cfg, scope)


def test_cleanup_readback_rejects_symlinked_inbox_state(monkeypatch):
    import dataclasses
    import os
    import tempfile
    with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
        parent = Path(directory)
        state = parent / 'state'; state.mkdir(mode=0o700)
        inbox = state / 'github-inbox'; inbox.mkdir(mode=0o700)
        target = parent / 'other.json'; target.write_text('{"enabled": false}')
        (inbox / 'state.json').symlink_to(target)
        cfg = dataclasses.replace(plan(), state=state, uid=os.geteuid())
        ops = host.HostOperations(cfg, runner=FakeRunner())
        ops.enrollment_inode = str(inbox.stat().st_ino)
        ops.baseline = ('', '')
        with pytest.raises((PermissionError, OSError, ValueError)):
            ops.cleanup_readback(())


def test_partial_proxy_start_never_guesses_resource_identity_or_cleans():
    runner = FakeRunner(fail='up -d')
    operations = host.HostOperations(plan(), runner=runner)
    with pytest.raises(TimeoutError):
        operations.start_isolation()
    assert any('up -d' in ' '.join(call[0]) for call in runner.calls)
    assert not any(' stop ' in ' '.join(call[0]) or ' rm ' in ' '.join(call[0])
                   for call in runner.calls)


def test_foreign_container_identity_blocks_cleanup_without_remove():
    runner = FakeRunner()
    operations = host.HostOperations(plan(), runner=runner)
    operations.worker_id = 'a' * 64
    operations.proxy_id = 'b' * 64
    owned = (host.Owned('worker', operations.worker_id, 'attempt1'),)
    runner.__call__ = runner.__call__
    assert operations.inspect_owned(owned) is False
    assert not any('stop' in call[0] or 'rm' in call[0] for call in runner.calls)


def test_bounded_command_clamps_to_overall_budget_and_suppresses_output(monkeypatch):
    calls = []
    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        class Result: returncode = 0; stdout = b'safe'; stderr = b''
        return Result()
    monkeypatch.setattr(host.subprocess, 'run', fake_run)
    shell = host.CommandRunner(deadline=host.time.monotonic() + 2)
    assert shell(['docker', 'ps'], timeout=300) == 'safe'
    assert len(calls) == 1 and 0 < calls[0][1]['timeout'] <= 2
    assert calls[0][1]['capture_output'] is True and calls[0][1]['check'] is True
    assert calls[0][1]['env']['PATH'] == '/usr/sbin:/sbin:/usr/bin:/bin'


def test_command_runner_sanitizes_inherited_and_supplied_path(monkeypatch):
    monkeypatch.setenv('PATH', '/untrusted/parent')
    calls = []
    def fake_run(argv, **kwargs):
        calls.append(kwargs['env'])
        class Result: stdout = b''; stderr = b''
        return Result()
    monkeypatch.setattr(host.subprocess, 'run', fake_run)
    host.CommandRunner(deadline=host.time.monotonic() + 10)(
        ['iptables', '-S'], timeout=5, env={'PATH': '/untrusted/caller'})
    assert calls[0]['PATH'] == '/usr/sbin:/sbin:/usr/bin:/bin'


def test_preflight_rejects_missing_admin_tool_before_any_command(monkeypatch):
    import shutil
    monkeypatch.setattr(host.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(shutil, 'which', lambda name, path=None: None if name == 'iptables' else '/usr/bin/' + name)
    runner = FakeRunner()
    with pytest.raises(FileNotFoundError, match='iptables'):
        host.HostOperations(plan(), runner=runner).preflight()
    assert runner.calls == []
