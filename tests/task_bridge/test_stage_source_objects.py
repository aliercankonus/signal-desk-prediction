"""Real local Git transfer with only the public-network transport substituted."""
import importlib.util
import ast
import hashlib
import io
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load():
    spec = importlib.util.spec_from_file_location(
        'source_objects', ROOT / 'ops/bridge_one_shot/stage_source_objects.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(folder, *args):
    return subprocess.check_output(
        ['git', '-C', str(folder), *args], stderr=subprocess.DEVNULL).strip().decode()


@pytest.fixture
def local_store(monkeypatch):
    if os.geteuid() != 0:
        pytest.skip('production root-only policy is not weakened for non-root fixtures')
    module = load()
    with tempfile.TemporaryDirectory(dir=Path.home()) as folder:
        root = Path(folder)
        remote, store = root / 'remote', root / 'store'
        remote.mkdir(mode=0o700)
        store.mkdir(mode=0o700)
        git(remote, 'init', '-q')
        git(remote, 'config', 'user.name', 'Offline test')
        git(remote, 'config', 'user.email', 'test@example.invalid')
        pins = []
        for index in range(5):
            (remote / 'fixture').write_text(str(index))
            git(remote, 'add', '.')
            git(remote, 'commit', '-qm', 'offline fixture')
            pins.append(git(remote, 'rev-parse', 'HEAD'))
        git(store, 'init', '--bare', '-q')
        git(store, 'fetch', str(remote), pins[0] + ':refs/heads/preserved')
        before = module.snapshot(store, module.run_git)
        monkeypatch.setattr(module, 'PINS', (pins[2], pins[1], pins[0], pins[3], pins[4]))
        monkeypatch.setattr(module, 'SOURCE', pins[4])
        real_popen = subprocess.Popen
        seen = []

        def local_transport(argv, **kwargs):
            seen.append(tuple(argv))
            assert argv[0] == '/usr/bin/git'
            assert kwargs['env'] == module.ENV
            assert kwargs['stdin'] is subprocess.DEVNULL
            assert kwargs['stderr'] is subprocess.DEVNULL
            assert kwargs['start_new_session'] is True
            if 'fetch' in argv:
                # Production command/options are checked BEFORE substitution.
                assert tuple(argv[-len(module.FETCH):]) == module.FETCH
                assert 'credential.helper=' in argv
                assert 'core.hooksPath=/dev/null' in argv
                assert '--no-write-fetch-head' in argv
                assert '--no-auto-maintenance' in argv
                assert '--no-tags' in argv and '--no-recurse-submodules' in argv
                argv = list(argv)
                argv[argv.index('protocol.file.allow=never')] = 'protocol.file.allow=always'
                argv[-2:] = [str(remote), pins[4]]
            return real_popen(argv, **kwargs)

        monkeypatch.setattr(subprocess, 'Popen', local_transport)
        yield module, store, before, seen, local_transport


def test_preview_never_fetches_or_changes_existing_refs(local_store, capsys):
    m, store, before, seen, _ = local_store
    m.prepare(str(store))
    assert m.snapshot(store, m.run_git) == before
    assert not any('fetch' in argv for argv in seen)
    assert 'no changes made' in capsys.readouterr().out


def test_adds_only_pinned_objects_preserves_head_refs_fetch_head_and_no_second_fetch(
        local_store, capsys):
    m, store, before, seen, _ = local_store
    m.prepare(str(store), apply=True)
    assert all(m.present(store, pin, m.run_git) for pin in m.PINS)
    assert m.snapshot(store, m.run_git) == before
    assert sum('fetch' in argv for argv in seen) == 1
    m.prepare(str(store), apply=True)
    assert sum('fetch' in argv for argv in seen) == 1
    assert m.snapshot(store, m.run_git) == before
    output = capsys.readouterr().out
    assert 'SOURCE_OBJECTS: VERIFIED' in output and 'OVERALL: NO-GO' in output
    assert str(store) not in output and m.SOURCE not in output
    assert all('checkout' not in argv and 'reset' not in argv and 'clean' not in argv
               and 'chown' not in argv for argv in seen)


@pytest.mark.parametrize('condition', ['auth_config', 'shallow', 'head_symlink'])
def test_unsafe_existing_state_stops_without_fetch_or_repair(local_store, condition):
    m, store, _, seen, _ = local_store
    if condition == 'auth_config':
        # Setup via run_git, not a production config write.
        result = subprocess.Popen(
            ['/usr/bin/git', *m.OPTIONS, '--git-dir=' + str(store),
             'config', 'http.extraHeader', 'synthetic fixture'],
            env=m.ENV, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, start_new_session=True)
        result.communicate()
        assert result.returncode == 0
    elif condition == 'shallow':
        (store / 'shallow').write_text('synthetic\n')
    else:
        (store / 'HEAD').unlink()
        (store / 'HEAD').symlink_to('config')
    with pytest.raises(m.Stop):
        m.prepare(str(store), apply=True)
    assert not any('fetch' in argv for argv in seen)


def test_failed_transfer_preserves_refs_and_does_not_retry(local_store, monkeypatch):
    m, store, before, seen, transport = local_store
    calls = []
    def unavailable(argv, **kwargs):
        if 'fetch' in argv:
            calls.append(tuple(argv))
            raise OSError('private transport diagnostics must not be exposed')
        return transport(argv, **kwargs)
    monkeypatch.setattr(subprocess, 'Popen', unavailable)
    with pytest.raises(OSError):
        m.prepare(str(store), apply=True)
    assert len(calls) == 1
    assert m.snapshot(store, m.run_git) == before


def test_nonroot_and_symlink_store_are_rejected_before_commands(monkeypatch, tmp_path):
    m = load()
    def forbidden(*a, **kw):
        pytest.fail('untrusted store reached Git')
    monkeypatch.setattr(m.os, 'geteuid', lambda: 10000)
    with pytest.raises(m.Stop, match='ROOT_REQUIRED'):
        m.prepare(str(tmp_path), apply=True, run=forbidden)
    monkeypatch.setattr(m.os, 'geteuid', lambda: 0)
    link = tmp_path / 'alias'
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(m.Stop):
        m.prepare(str(link), apply=True, run=forbidden)


def test_sanitized_main_and_explicit_apply_argument(monkeypatch, capsys):
    m = load()
    monkeypatch.setattr(sys, 'argv', ['source', '--store', '/not-a-real-private-path'])
    assert m.main() == 1
    output = capsys.readouterr().out
    assert 'STOP:' in output and '/not-a-real-private-path' not in output


def test_git_subprocess_deadline_and_output_bound_kill_only_own_group(monkeypatch):
    m = load()
    writers, killed = [], []
    class Child:
        pid = 76543
        def __init__(self, payload):
            readable, writable = os.pipe()
            writers.append(writable)
            self.stdout = os.fdopen(readable, 'rb', buffering=0)
            if payload:
                os.write(writable, payload)
        def poll(self):
            return None
        def wait(self, timeout=None):
            return 0
    monkeypatch.setattr(m.os, 'killpg', lambda pid, sig: killed.append((pid, sig)))
    monkeypatch.setattr(m.subprocess, 'Popen', lambda *a, **kw: Child(b''))
    with pytest.raises(m.Stop, match='TIMEOUT'):
        m.run_git('/synthetic', ('rev-parse', '--is-bare-repository'), seconds=.01)
    os.close(writers.pop())
    # Keep the fixture pipe below kernel capacity; shrink the read limit by
    # feeding many readable chunks through a temporary regular file instead.
    with tempfile.TemporaryFile() as stream:
        stream.write(b'x' * 65537)
        stream.seek(0)
        class LargeChild(Child):
            def __init__(self):
                self.stdout = os.fdopen(os.dup(stream.fileno()), 'rb', buffering=0)
        monkeypatch.setattr(m.subprocess, 'Popen', lambda *a, **kw: LargeChild())
        # select() supports regular files; epoll does not.
        monkeypatch.setattr(m.selectors, 'DefaultSelector', m.selectors.SelectSelector)
        with pytest.raises(m.Stop, match='OUTPUT_BOUND'):
            m.run_git('/synthetic', ('for-each-ref',))
    assert killed == [(76543, signal.SIGKILL), (76543, signal.SIGKILL)]


@pytest.mark.parametrize('case', ['valid', 'digest_mismatch', 'oversize', 'missing_fields'])
def test_copyable_immutable_entry_syntax_integrity_and_explicit_source_only_apply(
        monkeypatch, capsys, case):
    import urllib.request
    doc = (ROOT / 'ops/bridge_one_shot/STAGE_SOURCE_OBJECTS.md').read_text()
    shell = doc.split('```bash\n', 1)[1].split('\n```', 1)[0] + '\n'
    assert subprocess.run(['bash', '-n'], input=shell, text=True,
                          capture_output=True).returncode == 0
    code = re.search(r"<<'PY'\n(.*?)\nPY\n", shell, re.S).group(1)
    ast.parse(code)
    payload = b"print('OFFLINE_ENTRY_EXECUTED')\n"
    if case == 'oversize':
        payload = b'x' * 32769
    monkeypatch.setattr(os, 'geteuid', lambda: 0)
    monkeypatch.setenv('SD_SOURCE_ENTRY_COMMIT', '1' * 40)
    monkeypatch.setenv('SD_SOURCE_ENTRY_SHA256', hashlib.sha256(payload).hexdigest())
    monkeypatch.setenv('SD_SOURCE_STORE', '/synthetic-private-source')
    if case == 'digest_mismatch':
        monkeypatch.setenv('SD_SOURCE_ENTRY_SHA256', '0' * 64)
    if case == 'missing_fields':
        monkeypatch.delenv('SD_SOURCE_ENTRY_COMMIT')
    requested = []
    def offline(url, timeout):
        requested.append((url, timeout))
        assert url.startswith('https://raw.githubusercontent.com/aliercankonus/signal-desk-prediction/')
        assert url.endswith('/ops/bridge_one_shot/stage_source_objects.py')
        return io.BytesIO(payload)
    monkeypatch.setattr(urllib.request, 'urlopen', offline)
    # Keep the test runner's argv intact when exercising the real loader.
    monkeypatch.setattr(sys, 'argv', list(sys.argv))
    if case == 'valid':
        exec(compile(code, '<offline-loader>', 'exec'), {})
        assert sys.argv == ['stage_source_objects.py', '--store', '/synthetic-private-source', '--apply']
    else:
        with pytest.raises(SystemExit, match='STOP:'):
            exec(compile(code, '<offline-loader>', 'exec'), {})
    output = capsys.readouterr().out
    assert ('OFFLINE_ENTRY_EXECUTED' in output) == (case == 'valid')
    assert '/synthetic-private-source' not in output
    assert len(requested) == (0 if case == 'missing_fields' else 1)
