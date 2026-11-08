"""Offline, one-shot manager signer regressions; no GitHub/provider calls."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import time

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('root_signer', ROOT / 'ops/github_inbox/root_signer.py')
assert SPEC and SPEC.loader
import sys
signer = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = signer
SPEC.loader.exec_module(signer)

IDENTITY = 'a' * 64
RUNNER = 'e84021a786004456a12de9e25eae50d191da6cf1'
BODY = 'frozen task body'
APP = 1144995

def scope():
    return signer.Scope(repo='aliercankonus/signal-desk-prediction', task_issue=43,
        body_digest=hashlib.sha256(BODY.encode()).hexdigest(), authority_identity=IDENTITY,
        runner_commit=RUNNER, start='2026-11-08T00:00:00Z', cursors={'41': 100, '45': 200},
        app_id=APP)

class FakeGitHub:
    def __init__(self, issue=41, comment_id=101):
        self.issue = issue
        self.comment_id = comment_id
        self.post_count = 0
        self.posts = {}
        self.fail_post = False
        self.edit_on_refetch = False
        self.rate_limit = False
        self.events = []
    def task(self, issue):
        self.events.append('task_get')
        return {'number': issue, 'state': 'open', 'body': BODY}
    def comment(self, issue, comment_id):
        self.events.append('comment_get')
        if comment_id in self.posts:
            return {'id': comment_id, 'issue_url': f'https://api.github.com/repos/aliercankonus/signal-desk-prediction/issues/{issue}',
                    'body': self.posts[comment_id], 'created_at': '2026-11-08T00:10:00Z',
                    'updated_at': '2026-11-08T00:10:00Z'}
        if self.rate_limit:
            raise signer.RateLimited()
        changed = self.edit_on_refetch and self.events.count('comment_get') > 1
        return {'id': comment_id,
                'issue_url': f'https://api.github.com/repos/aliercankonus/signal-desk-prediction/issues/{self.issue}',
                'body': f'RUN FROZEN DEVELOPMENT TASK #43 AUTH {IDENTITY}' + (' tampered' if changed else ''),
                'created_at': '2026-11-08T00:05:00Z',
                'updated_at': '2026-11-08T00:06:00Z' if changed else '2026-11-08T00:05:00Z',
                'performed_via_github_app': {'id': APP}}
    def publish(self, issue, body):
        self.events.append('post')
        self.post_count += 1
        self.posts[300] = body
        if self.fail_post:
            raise TimeoutError('lost POST response')
        return 300

@pytest.fixture
def private_root():
    with tempfile.TemporaryDirectory(dir=Path.home(), prefix='sd-signer-test-') as name:
        yield Path(name)

def test_signer_claims_before_signature_and_posts_one_canonical_grant(private_root):
    client = FakeGitHub()
    signed = []
    def sign(data):
        assert (private_root / '101' / 'state.json').is_file()
        assert json.loads((private_root / '101' / 'state.json').read_text())['phase'] == 'claimed'
        signed.append(data)
        return b'x' * 64
    grant = signer.sign_once(scope(), private_root, client, 41, 101, sign,
        verify=lambda payload, signature: signature == b'x' * 64)
    assert len(signed) == 1 and client.post_count == 1
    assert grant['status'] == 'verified' and grant['grant_id'] == 300
    envelope = json.loads(client.posts[300])['signal_desk_grant_v1']
    assert signed[0] == signer.canonical(envelope['payload'])
    assert envelope['payload']['instruction_sha256'] == hashlib.sha256(
        f'RUN FROZEN DEVELOPMENT TASK #43 AUTH {IDENTITY}'.encode()).hexdigest()
    assert client.events.index('post') > client.events.index('comment_get')
    with pytest.raises(FileExistsError):
        signer.sign_once(scope(), private_root, client, 41, 101, sign)
    assert client.post_count == 1 and len(signed) == 1

@pytest.mark.parametrize('mutate', ('app', 'edited', 'old', 'wrong_issue', 'wrong_body', 'task_body'))
def test_forged_or_changed_instruction_never_signs(private_root, mutate):
    client = FakeGitHub()
    old = client.comment
    def comment(issue, comment_id):
        row = old(issue, comment_id)
        if mutate == 'app': row['performed_via_github_app'] = {'id': 0}
        if mutate == 'edited': row['updated_at'] = '2026-11-08T00:06:00Z'
        if mutate == 'old': row['created_at'] = row['updated_at'] = '2026-11-07T00:00:00Z'
        if mutate == 'wrong_issue': row['issue_url'] = row['issue_url'].replace('/41', '/45')
        if mutate == 'wrong_body': row['body'] += ' arbitrary'
        return row
    client.comment = comment
    if mutate == 'task_body': client.task = lambda issue: {'number': 43, 'state': 'open', 'body': 'changed'}
    def forbidden(_): raise AssertionError('signed')
    with pytest.raises(ValueError):
        signer.sign_once(scope(), private_root, client, 41, 101, forbidden)
    assert client.post_count == 0

@pytest.mark.parametrize('mode', ('refetch_edit', 'lost_post', 'rate_limit', 'crash_after_claim'))
def test_uncertain_or_changed_instruction_never_replays(private_root, mode):
    client = FakeGitHub()
    client.edit_on_refetch = mode == 'refetch_edit'
    client.fail_post = mode == 'lost_post'
    client.rate_limit = mode == 'rate_limit'
    calls = []
    def sign(_):
        calls.append('sign')
        if mode == 'crash_after_claim':
            raise RuntimeError('synthetic signer crash')
        return b'x' * 64
    with pytest.raises((ValueError, TimeoutError, signer.RateLimited, RuntimeError)):
        signer.sign_once(scope(), private_root, client, 41, 101, sign,
            verify=lambda payload, signature: signature == b'x' * 64)
    with pytest.raises((FileExistsError, signer.RateLimited)):
        signer.sign_once(scope(), private_root, client, 41, 101, sign)
    assert client.post_count <= 1 and len(calls) <= 1
    if mode == 'lost_post':
        assert json.loads((private_root / '101' / 'state.json').read_text())['phase'] == 'post-intent'
    if mode == 'crash_after_claim':
        assert json.loads((private_root / '101' / 'state.json').read_text())['phase'] == 'claimed'

def test_real_ephemeral_ed25519_matches_inbox_verifier(private_root):
    import subprocess
    sys.path.insert(0, str(ROOT / 'autonomous-development'))
    from github_inbox import verify_grant
    key = private_root / 'test-key.pem'
    public = private_root / 'test-public.pem'
    subprocess.run(['openssl', 'genpkey', '-algorithm', 'ed25519', '-out', str(key)],
                   capture_output=True, check=True, timeout=10)
    key.chmod(0o600)
    with public.open('wb') as stream:
        subprocess.run(['openssl', 'pkey', '-in', str(key), '-pubout'],
                       stdout=stream, stderr=subprocess.DEVNULL, check=True, timeout=10)
    public.chmod(0o600)
    client = FakeGitHub()
    grant = signer.sign_once(scope(), private_root, client, 41, 101,
        lambda payload: signer.openssl_sign(key, payload),
        verify=lambda payload, signature: signer.openssl_verify(public, payload, signature))
    assert grant['status'] == 'verified'
    envelope = json.loads(client.posts[300])
    assert verify_grant(envelope, public.read_bytes())['authority_identity'] == IDENTITY


def test_cursor_and_task_identity_replay_rejected(private_root):
    client = FakeGitHub()
    with pytest.raises(ValueError):
        signer.sign_once(scope(), private_root, client, 41, 100, lambda _: b'x' * 64)
    with pytest.raises(ValueError):
        signer.sign_once(scope(), private_root, client, 45, 101, lambda _: b'x' * 64)
    assert client.post_count == 0


def test_drip_fed_http_response_is_cut_off_by_whole_request_deadline(monkeypatch):
    class Response:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def read(self, limit):
            time.sleep(0.2)  # Simulates a socket drip-feed, no network.
            return b'{}'
    class Opener:
        def open(self, request, timeout): return Response()
    monkeypatch.setattr(signer.urllib.request, 'build_opener', lambda *_: Opener())
    client = signer.GitHub.__new__(signer.GitHub)
    client._token = 'synthetic-offline-token'
    client.deadline = time.monotonic() + 0.04
    with pytest.raises(TimeoutError, match='deadline'):
        client.task(43)


def test_root_readback_accepts_only_frozen_artifact_contents_get(monkeypatch):
    class Response:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def read(self, limit): return b'{}'
    class Opener:
        def open(self, request, timeout):
            assert request.get_method() == 'GET'
            return Response()
    monkeypatch.setattr(signer.urllib.request, 'build_opener', lambda *_: Opener())
    client = signer.GitHub.__new__(signer.GitHub)
    client._token = 'synthetic-offline-token'
    client.deadline = time.monotonic() + 2
    path = f'/repos/{signer.REPO}/contents/docs/ONE_SHOT_REVIEW_NOTE.md?ref={RUNNER}'
    assert client.get(path) == {}
    with pytest.raises(ValueError, match='outside fixed scope'):
        client.get(path.replace('ONE_SHOT_REVIEW_NOTE', 'OTHER'))


def test_slow_multipage_scan_stops_at_shared_deadline(private_root, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(time, 'monotonic', lambda: clock[0])

    class SlowPages(FakeGitHub):
        def candidates(self, issue, start, *, deadline=None):
            assert deadline == 103.0
            for page in range(5):
                self.events.append((issue, page))
                clock[0] += 0.8
                yield {'id': 102 + page, 'body': 'not an instruction'}

    client = SlowPages()
    with pytest.raises(TimeoutError, match='deadline'):
        signer.sign_scan(scope(), private_root, client, lambda _: (_ for _ in ()).throw(
            AssertionError('signed')), verify=lambda *_: True, deadline=103.0)
    assert client.events == [(41, 0), (41, 1), (41, 2), (41, 3)]
    assert not list(private_root.iterdir())
