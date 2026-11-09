"""Real Git reads of frozen public bytes; ref lookup and Docker are offline fixtures."""
import hashlib
import ast
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import tempfile

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load():
    spec = importlib.util.spec_from_file_location(
        'setup_workspace', ROOT / 'ops/bridge_one_shot/prepare_setup_workspace.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def fixture(monkeypatch):
    if os.geteuid() != 0:
        pytest.skip('root-only preparation policy is unchanged')
    module = load()
    with tempfile.TemporaryDirectory(dir=Path.home()) as folder:
        root = Path(folder)
        source, parent = root / 'source.git', root / 'new-setup'
        # The collector deliberately excludes .git. Build synthetic Git history
        # containing the exact reviewed bytes, with hash gates unchanged. Only
        # fixed historical ref lookup is mapped below, never production policy.
        repo = root / 'fixture-repo'
        repo.mkdir(mode=0o700)
        for name in (*module.FILES, 'operator_bootstrap.py'):
            original = ROOT / 'ops/bridge_one_shot' / name
            target = repo / 'ops/bridge_one_shot' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(original.read_bytes())
        for name, digest in module.FILES.items():
            assert hashlib.sha256((repo / 'ops/bridge_one_shot' / name).read_bytes()).hexdigest() == digest
        boot = (repo / 'ops/bridge_one_shot/operator_bootstrap.py').read_bytes()
        assert len(boot) == 26012
        assert hashlib.sha256(boot).hexdigest() == 'e79f337fcbefc4f21f4d6d4abd2e30078227cb0913f242b552630fd110c1dd0d'
        for args in (('init','-q'), ('config','user.name','Offline test'),
                     ('config','user.email','test@example.invalid'), ('add','.'),
                     ('commit','-qm','frozen public fixture')):
            subprocess.run(['git','-C',str(repo),*args], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        fixture_commit = subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD']).decode().strip()
        subprocess.run(['git', 'clone', '--bare', '--no-hardlinks', str(repo), str(source)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        source.chmod(0o700)
        legacy = root / 'old-runner'
        legacy.mkdir(mode=0o700)
        (legacy / 'preserved').write_text('historical checkpoint\n')
        real_popen = subprocess.Popen
        seen = []
        metadata = {'ids':['a' * 64], 'mounts':[
            {'Type':'bind','Source':'/synthetic-agent','Destination':'/opt/data'}]}
        def transport(argv, **kwargs):
            seen.append(tuple(argv))
            if argv[0] == 'docker':
                assert not any('Env' in value or 'exec' == value or 'run' == value for value in argv)
                if argv == ['docker', 'ps', '-aq', '--no-trunc']:
                    payload = '\n'.join(metadata['ids']) + '\n'
                else:
                    assert argv[:6] == ['docker','inspect','--type','container','--format','{{json .Mounts}}']
                    assert argv[-1] in metadata['ids']
                    payload = json.dumps(metadata['mounts'])
                argv = ['/usr/bin/python3', '-I', '-B', '-c',
                        'import sys;sys.stdout.write(' + repr(payload) + ')']
            else:
                assert argv[0] in ('/usr/bin/git', 'git')
                assert any(value.startswith('--git-dir=') for value in argv)
                assert not any(value in argv for value in ('fetch','checkout','reset','clean','push'))
                assert argv[-1].split(':', 1)[0] in (
                    module.PUBLIC_PIN, '665698113fcd7d8f7d10a75ee42f67d8a2131166')
                argv = [*argv[:-1], fixture_commit + ':' + argv[-1].split(':', 1)[1]]
            return real_popen(argv, **kwargs)
        monkeypatch.setattr(subprocess, 'Popen', transport)
        yield module, source, parent, legacy, seen, metadata


def test_real_public_blobs_install_fresh_root_workspace_only(fixture, capsys):
    m, source, parent, legacy, seen, _ = fixture
    m.prepare(str(source), str(parent), apply=True)
    assert stat.S_IMODE(parent.stat().st_mode) == 0o700
    assert set(path.name for path in parent.iterdir()) == set(m.FILES) | {'setup-manifest.json'}
    for name, digest in m.FILES.items():
        path = parent / name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
        assert path.stat().st_uid == 0 and stat.S_IMODE(path.stat().st_mode) == 0o600
    manifest = json.loads((parent / 'setup-manifest.json').read_text())
    assert manifest['runtime_authority'] is False and manifest['credential_provisioning'] is False
    assert (legacy / 'preserved').read_text() == 'historical checkpoint\n'
    output = capsys.readouterr().out
    assert 'SETUP_WORKSPACE: PREPARED' in output and 'OVERALL: NO-GO' in output
    assert str(parent) not in output and str(source) not in output
    assert not any('up' in argv or 'exec' in argv or 'run' in argv for argv in seen)


def test_preview_has_no_writes_and_existing_destination_is_never_reused(fixture, capsys):
    m, source, parent, _, _, _ = fixture
    m.prepare(str(source), str(parent))
    assert not parent.exists()
    assert 'WORKSPACE_PLAN: READY' in capsys.readouterr().out
    parent.mkdir(mode=0o700)
    (parent / 'preserved').write_text('existing')
    with pytest.raises(m.Stop, match='DESTINATION_EXISTS'):
        m.prepare(str(source), str(parent), apply=True)
    assert (parent / 'preserved').read_text() == 'existing'


@pytest.mark.parametrize('case', ['ancestor','descendant','volume','malformed','too_many'])
def test_mount_overlap_and_invalid_inventory_stop_before_creating_workspace(fixture, case):
    m, source, parent, _, _, metadata = fixture
    if case == 'ancestor':
        metadata['mounts'][0]['Source'] = str(parent.parent)
    elif case == 'descendant':
        metadata['mounts'][0]['Source'] = str(parent / 'child')
    elif case == 'volume':
        metadata['mounts'][0].update(Type='volume', Source=str(source))
    elif case == 'malformed':
        metadata['mounts'][0]['Source'] = 'relative'
    else:
        metadata['ids'] = [format(i, '064x') for i in range(33)]
    with pytest.raises(m.Stop):
        m.prepare(str(source), str(parent), apply=True)
    assert not parent.exists()


def test_digest_failure_precedes_docker_or_filesystem_writes(fixture, monkeypatch):
    m, source, parent, _, seen, _ = fixture
    monkeypatch.setitem(m.FILES, 'prepare_operator_spec.py', '0' * 64)
    with pytest.raises(m.Stop, match='PUBLIC_SOURCE_DIGEST'):
        m.prepare(str(source), str(parent), apply=True)
    assert not parent.exists()
    assert not any(argv[0] == 'docker' for argv in seen)


def test_nonroot_and_symlinked_parent_do_not_reach_public_reads(fixture, monkeypatch):
    m, source, parent, _, seen, _ = fixture
    monkeypatch.setattr(m.os, 'geteuid', lambda: 10000)
    with pytest.raises(m.Stop, match='ROOT_REQUIRED'):
        m.prepare(str(source), str(parent), apply=True)
    assert seen == []
    monkeypatch.setattr(m.os, 'geteuid', lambda: 0)
    alias = parent.with_name('alias')
    alias.symlink_to(parent.parent, target_is_directory=True)
    with pytest.raises(m.Stop):
        m.prepare(str(source), str(alias / 'new'), apply=True)
    assert seen == []


def test_partial_publication_is_preserved_and_not_retried(fixture, monkeypatch):
    m, source, parent, _, _, _ = fixture
    # Simulate interruption only after the first real exclusive public file write.
    # Replace the OS fsync at a meaningful point after directory/file publication.
    original_fsync = m.os.fsync
    calls = []
    def fail_after_first_file(fd):
        calls.append(fd)
        if len(calls) == 3:
            raise OSError('synthetic interrupted publication')
        return original_fsync(fd)
    monkeypatch.setattr(m.os, 'fsync', fail_after_first_file)
    with pytest.raises(OSError):
        m.prepare(str(source), str(parent), apply=True)
    assert parent.is_dir() and any(parent.iterdir())
    with pytest.raises(m.Stop, match='DESTINATION_EXISTS'):
        m.prepare(str(source), str(parent), apply=True)


def test_unconfigured_venv_metadata_does_not_execute_interpreter_or_modify_files(fixture):
    m, source, parent, legacy, _, _ = fixture
    m.prepare(str(source), str(parent), venv=str(legacy), apply=True)
    manifest = json.loads((parent / 'setup-manifest.json').read_text())
    assert manifest['venv_metadata']['status'] == 'UNPROVEN'
    assert stat.S_IMODE(legacy.stat().st_mode) == 0o700
    assert (legacy / 'preserved').read_text() == 'historical checkpoint\n'


def test_sanitized_cli_failure(monkeypatch, capsys):
    m = load()
    monkeypatch.setattr(sys, 'argv', ['setup', '--source', '/private-not-present',
                                     '--parent', '/private-not-present-new', '--apply'])
    assert m.main() == 1
    output = capsys.readouterr().out
    assert 'STOP:' in output and '/private-not-present' not in output


def test_public_blob_oversize_is_rejected_before_bytes_are_read(monkeypatch):
    m = load()
    seen = []
    def metadata_only(store, args):
        seen.append(args)
        assert args[:2] == ('cat-file', '-s')
        return b'32769\n'
    monkeypatch.setattr(m, 'git_read', metadata_only)
    with pytest.raises(m.Stop, match='PUBLIC_SOURCE_SIZE'):
        m.public_blob('/synthetic', 'prepare_operator_spec.py')
    assert len(seen) == 1


def test_public_reader_timeout_kills_only_its_own_git_group(monkeypatch):
    m = load()
    killed, waits = [], []
    class Child:
        pid = 76543
        stdout = io.BytesIO()
        def communicate(self, timeout):
            raise subprocess.TimeoutExpired('git', timeout)
        def poll(self):
            return None
        def wait(self, timeout):
            waits.append(timeout)
            return 0
    monkeypatch.setattr(m.subprocess, 'Popen', lambda *a, **kw: Child())
    monkeypatch.setattr(m.os, 'killpg', lambda pid, sig: killed.append((pid, sig)))
    with pytest.raises(subprocess.TimeoutExpired):
        m.git_read('/synthetic', ('cat-file', '-s', 'fixed-public-ref'))
    assert killed == [(76543, signal.SIGKILL)] and waits == [2]


@pytest.mark.parametrize('case', ['valid', 'digest_mismatch', 'oversize', 'missing_fields'])
def test_documented_loader_syntax_hash_before_execution_and_no_private_echo(
        monkeypatch, capsys, case):
    import urllib.request
    doc = (ROOT / 'ops/bridge_one_shot/PREPARE_SETUP_WORKSPACE.md').read_text()
    shell = doc.split('```bash\n', 1)[1].split('\n```', 1)[0] + '\n'
    assert subprocess.run(['bash', '-n'], input=shell, text=True,
                          capture_output=True).returncode == 0
    code = re.search(r"<<'PY'\n(.*?)\nPY\n", shell, re.S).group(1)
    ast.parse(code)
    payload = b"print('OFFLINE_SETUP_ENTRY')\n" if case != 'oversize' else b'x' * 32769
    monkeypatch.setattr(os, 'geteuid', lambda: 0)
    monkeypatch.setenv('SD_SETUP_ENTRY_COMMIT', '1' * 40)
    monkeypatch.setenv('SD_SETUP_ENTRY_SHA256', hashlib.sha256(payload).hexdigest())
    monkeypatch.setenv('SD_SETUP_SOURCE', '/synthetic-private-source')
    monkeypatch.setenv('SD_SETUP_PARENT', '/synthetic-private-setup')
    monkeypatch.setenv('SD_SETUP_VENV', '/synthetic-private-venv')
    if case == 'digest_mismatch':
        monkeypatch.setenv('SD_SETUP_ENTRY_SHA256', '0' * 64)
    if case == 'missing_fields':
        monkeypatch.delenv('SD_SETUP_PARENT')
    requested = []
    def offline(url, timeout):
        requested.append((url, timeout))
        assert url.startswith('https://raw.githubusercontent.com/aliercankonus/signal-desk-prediction/')
        assert url.endswith('/ops/bridge_one_shot/prepare_setup_workspace.py')
        return io.BytesIO(payload)
    monkeypatch.setattr(urllib.request, 'urlopen', offline)
    monkeypatch.setattr(sys, 'argv', list(sys.argv))
    if case == 'valid':
        exec(compile(code, '<offline-setup-loader>', 'exec'), {})
        assert sys.argv == ['prepare_setup_workspace.py', '--source', '/synthetic-private-source',
                            '--parent', '/synthetic-private-setup', '--venv', '/synthetic-private-venv', '--apply']
    else:
        with pytest.raises(SystemExit, match='STOP:'):
            exec(compile(code, '<offline-setup-loader>', 'exec'), {})
    output = capsys.readouterr().out
    assert ('OFFLINE_SETUP_ENTRY' in output) == (case == 'valid')
    assert '/synthetic-private' not in output
    assert len(requested) == (0 if case == 'missing_fields' else 1)
