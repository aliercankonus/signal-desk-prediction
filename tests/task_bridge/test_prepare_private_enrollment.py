"""Cold-input tests: real protected public files/Git, fake Docker and GitHub."""
import builtins
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import pty
import select
import stat
import sys
import termios
import threading
import time
import urllib.error

import pytest
from test_prepare_setup_workspace import fixture  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]
BODY = Path(__file__).with_name('frozen_issue43_body.txt').read_text()
ROOT_TOKEN = 'github_pat_' + 'offline_root_fixture_' * 3
WORKER_TOKEN = 'github_pat_' + 'offline_worker_fixture_' * 3
IMAGE = 'sha256:' + 'b' * 64


def load():
    spec = importlib.util.spec_from_file_location('cold_inputs', ROOT / 'ops/bridge_one_shot/prepare_private_enrollment.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture
def cold(fixture):
    setup, source, parent, legacy, seen, metadata = fixture
    setup.prepare(str(source), str(parent), apply=True)
    metadata['image'] = IMAGE
    m = load()
    calls = []
    def get(token, route, deadline):
        calls.append((token, route))
        assert route in m.READ_PATHS and deadline > time.monotonic()
        if token is None:
            assert route == m.READ_PATHS[2]
            return {'number':43, 'state':'open', 'body':BODY}
        assert token in (ROOT_TOKEN, WORKER_TOKEN)
        return {'/user':{'id':m.OWNER_ID, 'login':m.OWNER},
                m.READ_PATHS[1]:{'id':m.REPO_ID, 'full_name':m.REPO},
                m.READ_PATHS[3]:{'check_runs':[]},
                m.READ_PATHS[4]:{'workflow_runs':[]}}[route]
    secrets = iter((ROOT_TOKEN, WORKER_TOKEN))
    options = {'get':get, 'prompt':lambda *_:next(secrets),
               'keypair':lambda:(b'OFFLINE PRIVATE FIXTURE', b'OFFLINE PUBLIC FIXTURE'),
               'system_check':lambda:None}
    return m, parent, metadata, calls, options, seen


def test_cold_publication_and_host_only_receipt(cold, capsys):
    m, parent, _, calls, opts, seen = cold
    assert hashlib.sha256(BODY.encode()).hexdigest() == m.TASK_DIGEST
    m.prepare(str(parent), IMAGE, provision=True, **opts)
    for name in m.DESTINATIONS:
        info = (parent / name).stat()
        assert info.st_uid == 0 and stat.S_IMODE(info.st_mode) == 0o600
    assert (parent / 'root-github-token').read_text() == ROOT_TOKEN
    assert (parent / 'worker-github-token').read_text() == WORKER_TOKEN
    receipt = json.loads((parent / 'private-inputs-receipt.json').read_text())
    assert receipt['activation'] is False and receipt['task_authority'] is False
    assert receipt['worker_credentials_installed'] is False
    assert receipt['manager_app_exclusivity'] == 'UNPROVEN'
    assert 'host only' in receipt['read_evidence']
    assert len(calls) == 9
    out = capsys.readouterr().out
    assert ROOT_TOKEN not in out and WORKER_TOKEN not in out and str(parent) not in out
    assert 'PRIVATE_INPUTS: COLD_READY' in out and 'OVERALL: NO-GO' in out
    assert all('run' not in a and 'exec' not in a and 'up' not in a for a in seen)
    assert m.ENV_NAMES in [x for a in seen for x in a]
    assert '{{json .Config.Env}}' not in [x for a in seen for x in a]


def test_preview_never_prompts_or_generates_keys(cold):
    m, parent, _, _, opts, _ = cold
    def forbidden(*_):
        pytest.fail('preview reached credential effect')
    opts.update(prompt=forbidden, keypair=forbidden)
    before = set(parent.iterdir())
    m.prepare(str(parent), IMAGE, **opts)
    assert set(parent.iterdir()) == before


@pytest.mark.parametrize('case', ['same_token','classic','identity','repository','task','env','mount','volume','many_containers'])
def test_refusals_precede_publication(cold, case):
    m, parent, metadata, _, opts, _ = cold
    original = opts['get']
    if case == 'same_token':
        opts['prompt'] = lambda *_:ROOT_TOKEN
    elif case == 'classic':
        opts['prompt'] = lambda *_:'ghp_OFFLINE_INVALID_CLASSIC'
    elif case in ('identity','repository','task'):
        def get(token, route, deadline):
            data = original(token, route, deadline)
            if case == 'identity' and route == '/user': data['id'] = 1
            if case == 'repository' and route == m.READ_PATHS[1]: data['id'] = 1
            if case == 'task' and token is None: data['body'] += 'changed'
            return data
        opts['get'] = get
    elif case == 'env': metadata['env_names'] = 'PATH\nOLD_AUTH_TOKEN\n'
    elif case == 'many_containers': metadata['ids'] = [format(i, '064x') for i in range(33)]
    else:
        metadata['mounts'] = [{'Type':'volume' if case == 'volume' else 'bind',
                               'Source':str(parent.parent), 'Destination':'/synthetic'}]
    with pytest.raises(m.Stop): m.prepare(str(parent), IMAGE, provision=True, **opts)
    assert not any((parent / name).exists() for name in m.DESTINATIONS)


@pytest.mark.parametrize('name', ['private-inputs-intent.json','root-github-token','manager-key.pem'])
def test_existing_state_is_preserved_without_prompt_or_read(cold, name):
    m, parent, _, calls, opts, _ = cold
    target = parent / name
    target.symlink_to('/synthetic/nonexistent/private-state')
    with pytest.raises(m.Stop, match='PRESERVE_STATE'):
        m.prepare(str(parent), IMAGE, provision=True, **opts)
    assert target.is_symlink() and calls == []


def test_partial_publication_preserves_intent_and_prevents_retry(cold, monkeypatch):
    m, parent, _, calls, opts, _ = cold
    publish = m.publish
    def interrupted(folder, name, data):
        if name == 'manager-key.pem': raise InterruptedError()
        publish(folder, name, data)
    monkeypatch.setattr(m, 'publish', interrupted)
    with pytest.raises(InterruptedError): m.prepare(str(parent), IMAGE, provision=True, **opts)
    assert (parent / m.DESTINATIONS[0]).exists()
    calls.clear()
    with pytest.raises(m.Stop, match='PRESERVE_STATE'):
        m.prepare(str(parent), IMAGE, provision=True, **opts)
    assert calls == []


def test_root_files_and_publication_refuse_unsafe_types(cold):
    m, parent, _, _, _, _ = cold
    file = parent / 'test-input'
    file.write_text('public fixture')
    file.chmod(0o644)
    with pytest.raises(m.Stop): m.root_bytes(file, 128)
    file.chmod(0o600)
    assert m.root_bytes(file, 128) == b'public fixture'
    with pytest.raises(m.Stop): m.root_bytes(file, 1)
    with pytest.raises(m.Stop): m.publish(parent, 'outside', b'offline')
    m.publish(parent, 'root-github-token', b'offline')
    with pytest.raises(FileExistsError): m.publish(parent, 'root-github-token', b'replaced')
    assert (parent / 'root-github-token').read_bytes() == b'offline'


def test_supported_token_urls_have_no_broad_or_invented_scope():
    m = load()
    from urllib.parse import urlparse, parse_qs
    root = parse_qs(urlparse(m.token_template('root')).query)
    worker = parse_qs(urlparse(m.token_template('worker')).query)
    assert root['contents'] == ['read'] and worker['contents'] == ['write']
    assert root['issues'] == ['write'] and worker['pull_requests'] == ['write']
    assert root['expires_in'] == ['30']
    assert not {'checks','workflows','administration','secrets','repository_ids'} & root.keys()


def test_http_get_has_fixed_host_route_bounds_and_no_retry(monkeypatch):
    m = load()
    observed = []
    class Reply(io.BytesIO): pass
    class Opener:
        def open(self, request, timeout):
            observed.append(request)
            assert request.full_url == 'https://api.github.com/user'
            assert request.get_method() == 'GET'
            assert request.get_header('Authorization') == 'Bearer offline-test'
            return Reply(b'{"id":35579049}')
    def opener(handler):
        with pytest.raises(m.Stop, match='REDIRECT'): handler.redirect_request(None, None, None, None, None, None)
        return Opener()
    monkeypatch.setattr(m.urllib.request, 'build_opener', opener)
    assert m.github_get('offline-test', '/user', time.monotonic()+2)['id'] == m.OWNER_ID
    with pytest.raises(m.Stop): m.github_get('offline-test', '/repos/other/project', time.monotonic()+2)
    assert len(observed) == 1
    class Denied:
        def open(self, request, timeout):
            observed.append(request)
            raise urllib.error.HTTPError(request.full_url, 403, 'withheld', {}, None)
    monkeypatch.setattr(m.urllib.request, 'build_opener', lambda *_:Denied())
    with pytest.raises(m.Stop, match='GITHUB_HTTP_403'):
        m.github_get('offline-test', '/user', time.monotonic()+2)
    assert len(observed) == 2
    class Oversized:
        def open(self, *_args, **_kwargs): return Reply(b' ' * 65537)
    monkeypatch.setattr(m.urllib.request, 'build_opener', lambda *_:Oversized())
    with pytest.raises(m.Stop, match='RESPONSE_BOUND'):
        m.github_get('offline-test', '/user', time.monotonic()+2)


def test_real_tty_hides_input_and_restores_echo(monkeypatch):
    m = load()
    master, slave = pty.openpty()
    original = builtins.open
    def open_tty(file, *args, **kwargs):
        return original(os.dup(slave), 'r+b', buffering=0) if file == '/dev/tty' else original(file,*args,**kwargs)
    monkeypatch.setattr(builtins, 'open', open_tty)
    before = termios.tcgetattr(slave)
    captured = bytearray()
    errors = []
    def operator():
        try:
            assert select.select([master], [], [], 3)[0]
            captured.extend(os.read(master, 1024))
            assert not termios.tcgetattr(slave)[3] & termios.ECHO
            os.write(master, b'offline-hidden-token\n')
        except BaseException as exc: errors.append(exc)
    thread = threading.Thread(target=operator)
    thread.start()
    try:
        assert m.secret_input('Offline token', time.monotonic()+3) == 'offline-hidden-token'
        thread.join(4)
        assert not thread.is_alive() and not errors
        while select.select([master], [], [], 0)[0]: captured.extend(os.read(master, 1024))
        assert b'offline-hidden-token' not in captured
        assert termios.tcgetattr(slave) == before
    finally:
        os.close(master); os.close(slave)


def test_interrupted_tty_restores_echo(monkeypatch):
    m = load()
    master, slave = pty.openpty()
    original = builtins.open
    monkeypatch.setattr(builtins, 'open', lambda *_a, **_k:original(os.dup(slave), 'r+b', buffering=0))
    before = termios.tcgetattr(slave)
    def interrupted(*_): raise InterruptedError()
    monkeypatch.setattr(m.select, 'select', interrupted)
    try:
        with pytest.raises(InterruptedError): m.secret_input('Offline', time.monotonic()+2)
        assert termios.tcgetattr(slave) == before
    finally:
        os.close(master); os.close(slave)


def test_main_sanitizes_unexpected_exception(monkeypatch, capsys):
    m = load()
    monkeypatch.setattr(sys, 'argv', ['cold','--workspace','/synthetic','--image',IMAGE])
    def fail(*_args, **_kwargs): raise RuntimeError('offline-secret-value /synthetic/private/path')
    monkeypatch.setattr(m, 'prepare', fail)
    monkeypatch.setattr(m.resource, 'setrlimit', lambda *_:None)
    assert m.main() == 1
    output = capsys.readouterr().out
    assert 'offline-secret-value' not in output and '/synthetic/private/path' not in output
    assert 'STOP:' in output


def test_documented_loader_parses_and_checks_digest_before_execution(monkeypatch):
    import ast
    import subprocess
    m = load()
    doc = (ROOT / 'ops/bridge_one_shot/PREPARE_PRIVATE_ENROLLMENT.md').read_text()
    block = doc.split('```bash\n', 1)[1].split('```', 1)[0]
    subprocess.run(['bash','-n'], input=block.encode(), check=True)
    code = block.split("<<'PY'\n", 1)[1].rsplit('\nPY', 1)[0]
    ast.parse(code)
    marker = []
    payload = b'raise RuntimeError("offline-helper-executed")\n'
    class Reply(io.BytesIO): pass
    class Opener:
        def open(self, url, timeout):
            marker.append(url)
            return Reply(payload)
    monkeypatch.setattr(m.urllib.request, 'build_opener', lambda *_:Opener())
    monkeypatch.setattr(os, 'geteuid', lambda:0)
    for key, value in {'SD_PRIVATE_ENTRY_COMMIT':'a'*40,
                       'SD_PRIVATE_ENTRY_SHA256':'0'*64,
                       'SD_PRIVATE_WORKSPACE':'/synthetic/private-workspace',
                       'SD_PRIVATE_IMAGE':IMAGE}.items(): monkeypatch.setenv(key, value)
    with pytest.raises(SystemExit, match='FETCH_OR_DIGEST'): exec(code, {})
    monkeypatch.setenv('SD_PRIVATE_ENTRY_SHA256', hashlib.sha256(payload).hexdigest())
    with pytest.raises(RuntimeError, match='offline-helper-executed'): exec(code, {})
    assert len(marker) == 2 and all('/'+'a'*40+'/' in x for x in marker)


def test_system_crypto_is_fixed_ed25519_and_never_receives_secret_argv(monkeypatch):
    m = load()
    seen = []
    private, public = b'-----BEGIN PRIVATE KEY-----\nOFFLINE', b'-----BEGIN PUBLIC KEY-----\nOFFLINE'
    class Result:
        def __init__(self, value): self.stdout = value
    def run(argv, **kwargs):
        seen.append((argv, kwargs))
        assert argv[0] == '/usr/bin/openssl' and kwargs['stderr'] == m.subprocess.DEVNULL
        assert kwargs['env'] == m.ENV and kwargs['timeout'] == 10
        return Result(private if len(seen) == 1 else public)
    monkeypatch.setattr(m.subprocess, 'run', run)
    assert m.make_keypair() == (private, public)
    assert seen[0][0][1:] == ['genpkey','-algorithm','ED25519']
    assert seen[1][0][1:] == ['pkey','-pubout'] and seen[1][1]['input'] == private
    assert all(private.decode() not in arg for argv, _ in seen for arg in argv)
