"""Derived staging admission uses fake cold tokens, no credential reads/runtime."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest
from test_prepare_private_enrollment import cold, fixture, IMAGE, ROOT  # noqa: F401


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'ops/bridge_one_shot' / file)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


@pytest.fixture
def derived(cold, monkeypatch):
    policy, workspace, metadata, calls, options, seen = cold
    public = b'-----BEGIN PUBLIC KEY-----\nOFFLINE FIXTURE ONLY\n'
    options['keypair'] = lambda:(b'OFFLINE PRIVATE FIXTURE ONLY', public)
    policy.prepare(str(workspace), IMAGE, provision=True, **options)
    venv = workspace.parent / 'old-agent' / 'signal-desk-tooling/venvs/issue26-recovery-python314-20261030'
    venv.mkdir(parents=True, mode=0o700)
    (venv / 'pyvenv.cfg').write_text('offline metadata only')
    os.chown(venv, 10000, 10000); os.chown(venv / 'pyvenv.cfg', 10000, 10000)
    vm = {'path':str(venv),'status':'READY_METADATA_ONLY','uid':10000,'gid':10000,'mode':0o700}
    for name in ('setup-manifest.json','private-inputs-receipt.json'):
        path = workspace / name
        data = json.loads(path.read_text()); data['venv_metadata'] = vm
        path.write_text(json.dumps(data))
    m = load('derived_entry', 'stage_from_cold_inputs.py')
    getter = lambda commit, name:(ROOT / 'ops/bridge_one_shot' / name).read_bytes()
    original_module = m.module
    observed = {'stage':0,'credential_reads':0}
    def module(blob, name):
        result = original_module(blob, name)
        if name == 'cold_input_policy':
            reader = result.root_bytes
            def read(path, bound):
                assert path.name not in ('manager-key.pem','root-github-token','worker-github-token')
                return reader(path, bound)
            result.root_bytes = read
        if name == 'staging_v2':
            def command(argv, **kwargs):
                if argv[0] == 'git' and argv[2] == 'show':
                    if argv[-1].endswith(':ops/bridge_one_shot/operator_bootstrap.py'):
                        return (ROOT / 'ops/bridge_one_shot/operator_bootstrap.py').read_bytes()
                    assert argv[-1].endswith(':requirements.txt')
                    return (ROOT / 'requirements.txt').read_bytes()
                if argv[0] == 'git' and argv[2] == 'rev-parse': return b'true\n'
                if argv[0] == 'git' and argv[2] == 'cat-file': return b'commit\n'
                assert argv[:3] == ['docker','image','inspect'] and argv[4] == '{{.Id}}'
                return (IMAGE+'\n').encode()
            result.command = command
            def stage(cfg):
                assert (workspace / (m.ATTEMPT+'-bootstrap-spec.json')).exists()
                assert (workspace / (m.ATTEMPT+'-bootstrap.py')).exists()
                assert cfg['signer_token'] == str(workspace/'root-github-token')
                assert cfg['runner'].startswith(str(workspace))
                assert cfg['merge'] == 'eac843de7967d48cce56ee9a198750e98754a2de'
                assert result.RUNNER_PIN == 'e84021a786004456a12de9e25eae50d191da6cf1'
                observed['stage'] += 1
                return 'STAGED ONLY — offline fixture; no activation'
            result.stage = stage
        return result
    monkeypatch.setattr(m, 'module', module)
    return m, workspace, getter, observed


def test_real_manifest_admission_derives_spec_without_secret_reads(derived, capsys):
    m, workspace, getter, observed = derived
    before = set(workspace.iterdir())
    m.prepare(str(workspace), 'a'*40, {'41':1,'45':2}, getter=getter)
    assert set(workspace.iterdir()) == before and observed['stage'] == 0
    m.prepare(str(workspace), 'a'*40, {'41':1,'45':2}, getter=getter, stage=True)
    assert observed['stage'] == 1
    spec = json.loads((workspace/(m.ATTEMPT+'-bootstrap-spec.json')).read_text())
    assert spec['cursors'] == {'41':1,'45':2}
    assert spec['uid'] == 10000 and spec['gid'] == 10000
    receipt = json.loads((workspace/(m.ATTEMPT+'-staging-receipt.json')).read_text())
    assert receipt['activation'] is False and receipt['worker_credentials_installed'] is False
    assert receipt['manager_exclusive_invocation'] == 'UNPROVEN'
    assert str(workspace) not in capsys.readouterr().out
    with pytest.raises(m.Stop, match='EXISTING_PREPARATION'):
        m.prepare(str(workspace), 'a'*40, {'41':1,'45':2}, getter=getter, stage=True)
    assert observed['stage'] == 1


@pytest.mark.parametrize('case', ['receipt','intent','public_key','symlink','existing','venv','cursors','source_digest'])
def test_inconsistent_or_existing_input_blocks_before_effects(derived, case):
    m, workspace, getter, observed = derived
    cursors = {'41':1,'45':2}
    if case == 'source_digest': getter = lambda *_:b'changed public source'
    elif case == 'cursors': cursors['41'] = -1
    elif case == 'existing': (workspace/(m.ATTEMPT+'-bootstrap-spec.json')).touch()
    elif case == 'symlink':
        p = workspace/'worker-github-token'; p.unlink(); p.symlink_to('/synthetic/missing')
    elif case == 'public_key': (workspace/'manager-public.pem').write_bytes(b'changed public fixture')
    else:
        p = workspace / ('private-inputs-intent.json' if case=='intent' else 'private-inputs-receipt.json')
        data = json.loads(p.read_text())
        if case == 'venv': data['venv_metadata']['status'] = 'UNPROVEN'
        else: data['activation'] = True
        p.write_text(json.dumps(data))
    with pytest.raises((m.Stop, ValueError, PermissionError)):
        m.prepare(str(workspace), 'a'*40, cursors, getter=getter, stage=True)
    assert observed['stage'] == 0
    assert not (workspace/(m.ATTEMPT+'-bootstrap.py')).exists()


def test_v2_changes_only_the_names_boundary_and_retains_pins():
    original = (ROOT/'ops/bridge_one_shot/operator_bootstrap.py').read_text()
    revised = (ROOT/'ops/bridge_one_shot/operator_bootstrap_v2.py').read_text()
    a = original.index("    # Only the existing image's environment variable NAMES")
    b = original.index('    _contained_mounts', a)
    c = revised.index('    # Version 2:')
    d = revised.index('    _contained_mounts', c)
    assert original[:a] == revised[:c] and original[b:] == revised[d:]
    assert '{{json .Config.Env}}' not in revised


def test_v2_real_git_staging_retains_order_and_no_runtime(monkeypatch):
    import test_operator_bootstrap as old_tests
    revised = load('bootstrap_v2', 'operator_bootstrap_v2.py')
    original = revised.command
    names = []
    def command(argv, **kwargs):
        assert '{{json .Config.Env}}' not in argv
        if argv[:3] == ['docker','image','inspect'] and argv[4].startswith('{{range'):
            names.append(argv)
            return b'PATH\nHERMES_HOME\n\n'
        return original(argv, **kwargs)
    revised.command = command
    monkeypatch.setattr(old_tests, 'bootstrap', revised)
    old_tests.test_stages_from_real_local_git_without_runtime_or_credential_values(monkeypatch)
    assert len(names) == 1


def test_public_dependencies_and_operator_loader_are_bounded_and_hash_checked(monkeypatch):
    import ast
    import io
    import subprocess
    m = load('derived_source', 'stage_from_cold_inputs.py')
    class Reply(io.BytesIO): pass
    class Opener:
        def open(self, url, timeout):
            assert url.startswith('https://raw.githubusercontent.com/'+m.REPO+'/'+'a'*40+'/')
            assert timeout == 15
            return Reply(b'changed-public-code')
    monkeypatch.setattr(m.urllib.request, 'build_opener', lambda *_:Opener())
    with pytest.raises(m.Stop, match='DIGEST'): m.fetch_public('a'*40, 'operator_bootstrap_v2.py')
    with pytest.raises(m.Stop): m.fetch_public('main', 'operator_bootstrap_v2.py')
    with pytest.raises(m.Stop): m.fetch_public('a'*40, '../../private')
    doc = (ROOT/'ops/bridge_one_shot/STAGE_FROM_COLD_INPUTS.md').read_text()
    block = doc.split('```bash\n',1)[1].split('```',1)[0]
    subprocess.run(['bash','-n'], input=block.encode(), check=True)
    code = block.split("<<'PY'\n",1)[1].rsplit('\nPY',1)[0]
    ast.parse(code)
    assert code.index('hashlib.sha256(source)') < code.index('exec(compile(source')


def test_failed_staging_preserves_spec_and_never_calls_stage_twice(derived, monkeypatch):
    m, workspace, getter, observed = derived
    original = m.module
    def module(blob, name):
        result = original(blob,name)
        if name == 'staging_v2':
            def stage(cfg):
                observed['stage'] += 1
                raise InterruptedError()
            result.stage = stage
        return result
    monkeypatch.setattr(m, 'module', module)
    with pytest.raises(InterruptedError):
        m.prepare(str(workspace),'a'*40,{'41':1,'45':2},getter=getter,stage=True)
    assert (workspace/(m.ATTEMPT+'-bootstrap-spec.json')).exists()
    with pytest.raises(m.Stop, match='PRESERVE'):
        m.prepare(str(workspace),'a'*40,{'41':1,'45':2},getter=getter,stage=True)
    assert observed['stage'] == 1
