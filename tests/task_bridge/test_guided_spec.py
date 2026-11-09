"""Offline guided-spec boundary; no host Docker or credentials."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
DIRECTORY = ROOT / 'ops/bridge_one_shot'

def load(name):
    spec = importlib.util.spec_from_file_location(name, DIRECTORY / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

bootstrap = load('operator_bootstrap')
prepare = load('prepare_operator_spec')

@pytest.fixture
def fixture():
    with tempfile.TemporaryDirectory(dir=ROOT) as location:
        root = Path(location)
        for folder in ('source.git', 'fresh', 'private', 'venv', 'excluded-agent', 'excluded-app', 'excluded-release'):
            (root / folder).mkdir(mode=0o700)
        (root / 'venv/pyvenv.cfg').write_text('home = /synthetic\n')
        worker_uid = 12345 if os.geteuid() == 0 else os.geteuid()
        worker_gid = 12345 if os.geteuid() == 0 else os.getegid()
        if os.geteuid() == 0:
            os.chown(root / 'venv', worker_uid, worker_gid)
            os.chown(root / 'venv/pyvenv.cfg', worker_uid, worker_gid)
        for filename in ('key', 'public', 'token'):
            (root / 'private' / filename).write_bytes(b'synthetic fixture only')
            (root / 'private' / filename).chmod(0o600)
        values = dict(attempt='attempt-issue41', source=str(root/'source.git'), fresh_parent=str(root/'fresh'),
            private_parent=str(root/'private'), venv=str(root/'venv'), image='sha256:' + 'a'*64,
            uid=worker_uid, gid=worker_gid, signer_key=str(root/'private/key'),
            signer_public=str(root/'private/public'), signer_token=str(root/'private/token'),
            excluded_roots=[str(root/f'excluded-{name}') for name in ('agent','app','release')],
            requirements_sha256='b'*64, python_version='3.14.9', pytest_version='8.3.3',
            git_name='Reviewed Worker', git_email='reviewed@example.invalid',
            cursors={'41':6736705112,'45':1})
        calls = []
        def command(argv):
            calls.append(argv)
            if argv[:3] == ['docker', 'image', 'inspect']:
                return (values['image']+'\n').encode()
            if 'cat-file' in argv:
                return b'commit\n'
            if 'rev-parse' in argv:
                return b'true\n'
            if 'show' in argv:
                return (DIRECTORY / 'operator_bootstrap.py').read_bytes() if argv[-1].endswith(':ops/bridge_one_shot/operator_bootstrap.py') else b'synthetic requirements\n'
            raise AssertionError(argv)
        values['requirements_sha256'] = __import__('hashlib').sha256(b'synthetic requirements\n').hexdigest()
        yield root, values, command, calls


def test_prepared_record_is_exact_bootstrap_consumer_schema(fixture):
    root, values, command, calls = fixture
    cfg = prepare.prepare_spec(values, command=command, owner=os.geteuid(), now='2026-11-09T12:00:00Z')
    assert set(cfg) == bootstrap.SPEC_KEYS
    assert cfg['merge'] == bootstrap.MERGE
    assert cfg['signer_state_root'] == bootstrap.SIGNER_STATE
    assert cfg['task_body_sha256'] == bootstrap.TASK_DIGEST
    assert cfg['test_python'] == '/opt/data/signal-desk-tooling/venvs/issue26-recovery-python314-20261030/bin/python'
    assert cfg['plan'] == str(root/'private/attempt-issue41-operator-plan.json')
    assert cfg['start'] == '2026-11-09T12:00:00Z'
    assert bootstrap.validate_spec(cfg)
    assert any(a[:3] == ['docker','image','inspect'] for a in calls)
    assert not list((root/'private').glob('*.json'))


def test_missing_prerequisite_refuses_without_output_or_commands(fixture):
    root, values, command, calls = fixture
    Path(values['signer_token']).unlink()
    with pytest.raises((ValueError, PermissionError, FileNotFoundError), match='private input|prerequisite'):
        prepare.prepare_spec(values, command=command, owner=os.geteuid())
    assert len(calls) == 1 and calls[0][-1].endswith(':ops/bridge_one_shot/operator_bootstrap.py')
    assert not list(root.rglob('*.json'))


def test_placeholders_and_conflicting_fresh_paths_fail_before_any_effect(fixture):
    root, values, command, calls = fixture
    values['image'] = '<image-id>'
    with pytest.raises(ValueError, match='placeholder'):
        prepare.prepare_spec(values, command=command, owner=os.geteuid())
    assert calls == []
    values['image'] = 'sha256:'+'a'*64
    values['excluded_roots'].append(values['fresh_parent'])
    with pytest.raises(ValueError, match='overlap'):
        prepare.prepare_spec(values, command=command, owner=os.geteuid())
    assert not list(root.rglob('*.json'))


def test_exclusive_write_preserves_existing_spec_and_serializes_consumer_schema(fixture):
    root, values, command, calls = fixture
    cfg = prepare.prepare_spec(values, command=command, owner=os.geteuid())
    target = root/'private/attempt-issue41-bootstrap-spec.json'
    target.write_bytes(b'old record')
    with pytest.raises(FileExistsError):
        prepare.write_spec(target, cfg, owner=os.geteuid(), command=command)
    assert target.read_bytes() == b'old record'
    target.unlink()
    prepare.write_spec(target, cfg, owner=os.geteuid(), command=command)
    assert target.stat().st_mode & 0o777 == 0o600
    assert json.loads(target.read_bytes()) == cfg
    assert bootstrap.validate_spec(json.loads(target.read_bytes()))
    with pytest.raises(FileExistsError):
        prepare.write_spec(target, cfg, owner=os.geteuid(), command=command)


def test_consumer_loaded_from_pinned_source_without_prior_install(fixture):
    root, values, command, calls = fixture
    consumer = prepare.load_consumer(values['source'], command=command)
    assert consumer.SPEC_KEYS == bootstrap.SPEC_KEYS
    assert consumer.RUNNER_PIN == bootstrap.RUNNER_PIN
    def tampered(argv):
        if argv[-1].endswith(':ops/bridge_one_shot/operator_bootstrap.py'):
            return b'raise RuntimeError("must never execute unverified bytes")'
        return command(argv)
    with pytest.raises(ValueError, match='bootstrap source'):
        prepare.load_consumer(values['source'], command=tampered)


def test_missing_git_object_or_image_does_not_publish_spec(fixture):
    root, values, command, calls = fixture
    def bad(argv):
        return b'absent\n' if 'cat-file' in argv else command(argv)
    with pytest.raises(ValueError, match='source object'):
        prepare.prepare_spec(values, command=bad, owner=os.geteuid())
    assert not list(root.rglob('*.json'))
    def bad_image(argv):
        return b'wrong-image\n' if argv[:3] == ['docker','image','inspect'] else command(argv)
    with pytest.raises(ValueError, match='image'):
        prepare.prepare_spec(values, command=bad_image, owner=os.geteuid())
    assert not list(root.rglob('*.json'))
