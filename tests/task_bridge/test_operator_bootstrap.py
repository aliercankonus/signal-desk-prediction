"""Offline bootstrap contract: no Docker, network, credentials, signer or task effects."""
import hashlib
import importlib.util
import json
from pathlib import Path
import os
import subprocess
import sys
import tempfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / 'ops/bridge_one_shot/operator_bootstrap.py'
spec = importlib.util.spec_from_file_location('operator_bootstrap', MODULE)
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


def record(tmp):
    base = tmp / 'fresh'
    return dict(source=str(tmp / 'source.git'), merge='eac843de7967d48cce56ee9a198750e98754a2de',
                bundle=str(base / 'bundle'), runner=str(base / 'runner'), state=str(base / 'state'),
                auth=str(base / 'auth'), context=str(base / 'context'), home=str(base / 'home'),
                inbox=str(base / 'inbox'), journal_parent=str(base / 'journals'),
                signer_state_root='/var/lib/signal-desk/issue41-signer-claims',
                signer_key=str(tmp / 'private' / 'signer-key.pem'),
                signer_public=str(tmp / 'private' / 'signer-public.pem'),
                signer_token=str(tmp / 'private' / 'root-readback-token'),
                signer_policy=str(tmp / 'private' / 'signer-policy.json'),
                plan=str(tmp / 'private' / 'operator-plan.json'),
                venv=str(tmp / 'reviewed-venv'), image='sha256:' + 'a'*64,
                uid=12345, gid=12345, attempt='attempt-issue41', overall_seconds=1800,
                task_body_sha256='c9e4e393ccc506954f0a18e6eaeea7c82ff598b0b41eac642d7f88da1fca73c6',
                requirements_sha256='b'*64, python_version='3.14.9', pytest_version='8.3.3',
                test_python='/opt/data/signal-desk-tooling/venvs/issue26-recovery-python314-20261030/bin/python',
                start='2026-11-09T00:00:00Z', cursors={'41': 1, '45': 2},
                git_name='Reviewed Worker', git_email='reviewed-worker@example.invalid',
                excluded_roots=[str(tmp / 'existing-agent'), str(tmp / 'existing-release')])


def test_records_bind_approved_authority_context_enrollment_and_plan(tmp_path):
    cfg = record(tmp_path)
    records = bootstrap.build_records(cfg, b'public fixture only')
    policy = records['authorization.json']
    scope = records['signer-policy.json']
    assert policy == {'repo':'aliercankonus/signal-desk-prediction', 'issue':43,
                      'body_digest':cfg['task_body_sha256'], 'base':bootstrap.RUNNER_PIN,
                      'branch':'issue43-one-shot-review-note'}
    assert scope['authority_identity'] == hashlib.sha256(json.dumps(policy, sort_keys=True,
        separators=(',', ':')).encode()).hexdigest()
    assert records['enrollment.json']['public_key_sha256'] == hashlib.sha256(b'public fixture only').hexdigest()
    assert records['enrollment.json']['interval_seconds'] == 300
    assert records['operator-plan.json']['bundle'] == cfg['bundle']
    assert records['operator-plan.json']['signer_state_root'] == cfg['signer_state_root']
    assert records['context.json']['test_python'] == cfg['test_python']
    assert set(records['operator-plan.json']) == set(bootstrap.PLAN_KEYS)


def test_rejects_overlap_and_conflicting_destination_before_any_command(tmp_path):
    cfg = record(tmp_path)
    cfg['excluded_roots'].append(cfg['state'])
    with pytest.raises(ValueError, match='overlap'):
        bootstrap.validate_spec(cfg)
    cfg['excluded_roots'].pop()
    Path(cfg['bundle']).parent.mkdir()
    Path(cfg['bundle']).mkdir()
    with pytest.raises(FileExistsError):
        bootstrap.validate_spec(cfg)


def test_command_boundary_is_bounded_sanitized_and_never_executes(tmp_path):
    calls = []
    def fake(argv, *, timeout):
        calls.append((argv, timeout))
        return b''
    bootstrap.command(['git', 'cat-file', '-t', 'a'*40], run=fake)
    assert calls == [(['git', 'cat-file', '-t', 'a'*40], 15)]
    for argv, _ in calls:
        assert '--execute' not in argv and 'up' not in argv and 'tick' not in argv
    with pytest.raises(ValueError, match='command'):
        bootstrap.command(['sh', '-c', 'echo forbidden'], run=fake)
    assert len(calls) == 1


def test_real_subprocess_output_limit_stops_before_unbounded_capture():
    with pytest.raises(ValueError, match='output bound'):
        bootstrap._bounded_run([sys.executable, '-c', 'print("x" * 70000)'], timeout=3)


def test_staging_child_timeout_is_finite():
    with pytest.raises(TimeoutError, match='deadline'):
        bootstrap._bounded_run([sys.executable, '-c', 'import time; time.sleep(2)'], timeout=.05)


def test_existing_container_mount_overlap_blocks_staging_before_writes(monkeypatch, tmp_path):
    cfg = record(tmp_path)
    container = 'a' * 64
    def offline(argv, **_):
        if argv[:2] == ['docker','ps']:
            return (container + '\n').encode()
        assert argv[:2] == ['docker','inspect']
        return json.dumps([{'Type':'bind','Source':cfg['state'],'Destination':'/existing'}]).encode()
    monkeypatch.setattr(bootstrap, 'command', offline)
    with pytest.raises(PermissionError, match='existing container bind'):
        bootstrap._contained_mounts([Path(cfg['state']), Path(cfg['source'])])


def test_nearest_ancestor_checks_directory_not_private_file(tmp_path):
    with tempfile.TemporaryDirectory(dir=ROOT) as directory:
        parent = Path(directory) / 'private'
        parent.mkdir(mode=0o700)
        private_file = parent / 'key.pem'
        private_file.touch(mode=0o600)
        bootstrap._nearest(private_file.parent, os.geteuid())
        with pytest.raises(PermissionError):
            bootstrap._nearest(private_file, os.geteuid())


def test_missing_manager_exclusivity_remains_explicit_no_go(tmp_path):
    records = bootstrap.build_records(record(tmp_path), b'public fixture only')
    assert records['handoff.json']['manager_exclusive_invocation'] == 'UNPROVEN'
    assert records['handoff.json']['activation'] == 'NO-GO'
    assert records['handoff.json']['timer'] == 'DISABLED'


def test_durable_spec_and_staging_fence_do_not_auto_execute():
    sample = json.loads((ROOT / 'ops/bridge_one_shot/operator-bootstrap.spec.example.json').read_text())
    assert set(sample) == bootstrap.SPEC_KEYS
    handoff = (ROOT / 'ops/bridge_one_shot/BOOTSTRAP_HANDOFF.md').read_text()
    blocks = handoff.split('```sh\n')[1:]
    assert len(blocks) == 3
    stage_block = blocks[0].split('\n```', 1)[0]
    assert '--stage --spec' in stage_block and 'operator_host.py' not in stage_block
    assert 'STAGED ONLY' in stage_block
    assert 'operator_host.py" --execute' in blocks[-1]


def test_static_compose_rejects_root_secret_or_unexpected_worker_bind(tmp_path):
    cfg = record(tmp_path)
    rendered = compose_record(cfg)
    worker = rendered['services']['inbox-worker']['volumes']
    assert bootstrap.verify_compose(rendered, cfg) is None
    worker.append({'type':'bind','source':cfg['signer_key'], 'target':'/private/root/key', 'read_only':True})
    with pytest.raises(PermissionError, match='bind'):
        bootstrap.verify_compose(rendered, cfg)
    worker.pop()
    worker[0]['source'] = cfg['source']
    with pytest.raises(PermissionError, match='bind'):
        bootstrap.verify_compose(rendered, cfg)


def compose_record(cfg):
    worker = [{'type':'bind', 'source': cfg[k], 'target': t, 'read_only': k in ('auth','context','inbox','venv')}
              for k, t in [('runner','/workspace/runner'),('state','/state'),
                           ('auth','/private/auth'),('context','/private/context'),
                           ('home','/worker-home'),('venv','/opt/data/signal-desk-tooling/venvs/issue26-recovery-python314-20261030'),
                           ('inbox','/private/inbox')]]
    worker.append({'type':'bind','source':cfg['bundle'] + '/worker_probe.py',
                   'target':'/opt/worker-probe.py','read_only':True})
    proxy = [{'type':'bind','source':cfg['bundle'] + '/connect_proxy.py',
              'target':'/opt/connect-proxy.py','read_only':True}]
    return {'services':{'inbox-worker':{'volumes':worker,'restart':'no'},
                             'connect-proxy':{'volumes':proxy,'restart':'no'}}}


def test_stages_from_real_local_git_without_runtime_or_credential_values(monkeypatch):
    # Source is a local copy of committed Git objects. No remote access or
    # private key/token content is needed to exercise the staging contract.
    with tempfile.TemporaryDirectory(dir=ROOT) as directory:
        root = Path(directory)
        cfg = record(root)
        cfg['uid'] = max(1, os.geteuid())
        cfg['gid'] = max(1, os.getegid())
        (root / 'fresh').mkdir(mode=0o700)
        for excluded in cfg['excluded_roots']:
            Path(excluded).mkdir()
        Path(cfg['venv']).mkdir(mode=0o700)
        venv_config = Path(cfg['venv']) / 'pyvenv.cfg'
        venv_config.write_text('home = /reviewed/runtime\n')
        if os.geteuid() == 0:
            os.chown(Path(cfg['venv']), cfg['uid'], cfg['gid'])
            os.chown(venv_config, cfg['uid'], cfg['gid'])
        private = root / 'private'
        private.mkdir(mode=0o700)
        Path(cfg['signer_public']).write_bytes(b'-----BEGIN PUBLIC KEY-----\nfixture only\n')
        for key in ('signer_token', 'signer_key'):
            Path(cfg[key]).touch()  # existence only; no credential inputs in tests
        # CI copies source without .git; construct a real minimal two-commit
        # object store from the pinned inventory, never fabricate Git output.
        source_tree = root / 'source-tree'
        source_tree.mkdir()
        def git(*args):
            return subprocess.check_output(['git','-C',str(source_tree),
                '-c','user.name=Offline Fixture','-c','user.email=offline@example.invalid',
                *args], timeout=15).decode().strip()
        git('init','-q')
        (source_tree / 'requirements.txt').write_bytes((ROOT / 'requirements.txt').read_bytes())
        git('add','requirements.txt')
        git('commit','-q','-m','fixture runner')
        runner_pin = git('rev-parse','HEAD')
        for path in bootstrap.ARTIFACTS - {'ops/bridge_one_shot/operator_artifacts.json'}:
            target = source_tree / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / path).read_bytes())
        index = {'schema':1,'runner_commit':runner_pin,'files':sorted(bootstrap.ARTIFACTS)}
        (source_tree / 'ops/bridge_one_shot/operator_artifacts.json').write_text(json.dumps(index))
        git('add','ops')
        git('commit','-q','-m','fixture reviewed bundle')
        merge_pin = git('rev-parse','HEAD')
        subprocess.run(['git', 'clone', '--bare', '--no-hardlinks', '-q', str(source_tree), cfg['source']],
                       check=True, timeout=30)
        monkeypatch.setattr(bootstrap, 'RUNNER_PIN', runner_pin)
        monkeypatch.setattr(bootstrap, 'MERGE', merge_pin)
        cfg['merge'] = merge_pin
        requirements = subprocess.check_output(['git', '--git-dir=' + cfg['source'], 'show',
            bootstrap.RUNNER_PIN + ':requirements.txt'], timeout=15)
        cfg['requirements_sha256'] = hashlib.sha256(requirements).hexdigest()
        monkeypatch.setattr(bootstrap.os, 'geteuid', lambda: 0)
        monkeypatch.setattr(bootstrap.os, 'chown', lambda *_, **__: None)
        monkeypatch.setattr(bootstrap.os, 'fchown', lambda *_, **__: None)
        monkeypatch.setattr(bootstrap, '_trusted', lambda *_, **__: None)
        monkeypatch.setattr(bootstrap, '_regular', lambda *_, **__: None)
        mkdir = bootstrap._mkdir
        monkeypatch.setattr(bootstrap, '_mkdir', lambda path, owner, group:
            None if str(path) == bootstrap.SIGNER_STATE else mkdir(path, owner, group))
        original = bootstrap.command
        calls = []
        def offline(argv, *, run=None, env=None):
            calls.append(argv)
            if argv[:3] == ['docker', 'image', 'inspect']:
                return (cfg['image'] + '\n').encode() if '{{.Id}}' in argv else b'[]'
            if argv[:2] == ['docker', 'ps'] or argv[:2] == ['docker', 'network']:
                return b''
            if argv[:2] == ['docker', 'compose']:
                return json.dumps(compose_record(cfg)).encode()
            assert argv[0] == 'git'
            return original(argv, run=run)
        monkeypatch.setattr(bootstrap, 'command', offline)
        assert bootstrap.stage(cfg).startswith('STAGED ONLY')
        assert all('up' not in argv and '--execute' not in argv for argv in calls)
        assert json.loads(Path(cfg['plan']).read_text())['merge'] == bootstrap.MERGE
        assert json.loads(Path(cfg['signer_policy']).read_text())['authority_identity'] == (
            bootstrap.build_records(cfg, Path(cfg['signer_public']).read_bytes())['signer-policy.json']['authority_identity'])
        assert (Path(cfg['state']) / 'queue').is_dir()
        assert not (Path(cfg['state']) / 'github-inbox').exists()
        assert {x.name for x in Path(cfg['bundle']).iterdir()} == {
            Path(x).name for x in bootstrap.ARTIFACTS} | {'merged-byte-manifest.json'}
        with pytest.raises(FileExistsError):
            bootstrap.stage(cfg)


def test_image_mismatch_stops_before_staging_anything(monkeypatch):
    with tempfile.TemporaryDirectory(dir=ROOT) as directory:
        root = Path(directory)
        cfg = record(root)
        cfg['uid'] = max(1, os.geteuid())
        (root / 'fresh').mkdir(mode=0o700)
        for excluded in cfg['excluded_roots']:
            Path(excluded).mkdir()
        (root / 'private').mkdir()
        for key in ('signer_token','signer_key','signer_public'):
            Path(cfg[key]).touch()
        Path(cfg['signer_public']).write_bytes(b'-----BEGIN PUBLIC KEY-----\nfixture only\n')
        Path(cfg['venv']).mkdir()
        venv_config = Path(cfg['venv']) / 'pyvenv.cfg'
        venv_config.touch()
        if os.geteuid() == 0:
            os.chown(venv_config, cfg['uid'], cfg['uid'])
        monkeypatch.setattr(bootstrap.os, 'geteuid', lambda: 0)
        monkeypatch.setattr(bootstrap, '_trusted', lambda *_, **__: None)
        monkeypatch.setattr(bootstrap, '_regular', lambda *_, **__: None)
        monkeypatch.setattr(bootstrap, 'command', lambda argv, **_: b'wrong-image\n'
            if argv[:3] == ['docker','image','inspect'] else
            (b'commit\n' if 'cat-file' in argv else bootstrap.RUNNER_PIN.encode() + b'\n'
             if 'merge-base' in argv else b'{}'))
        with pytest.raises(ValueError, match='artifact inventory|image identity'):
            bootstrap.stage(cfg)
        assert not Path(cfg['bundle']).exists()
