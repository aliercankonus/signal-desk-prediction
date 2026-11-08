"""Dormant, operator-owned one-instruction signer. Never import from a task worker.

The source/key/policy and its invocation authority must be protected by the
operator OUTSIDE every worker mount. GitHub App metadata is an input, not proof
of manager-exclusive App invocation. No scheduler or key is installed here.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

REPO = 'aliercankonus/signal-desk-prediction'
ISSUES = (41, 45)
HEX40 = re.compile(r'[0-9a-f]{40}\Z')
HEX64 = re.compile(r'[0-9a-f]{64}\Z')
UTC = re.compile(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\Z')
MAX_STATE = 4096


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')


def trusted(path):
    for ancestor in (path, *path.parents):
        info = ancestor.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o022 or
                info.st_uid not in (0, os.geteuid())):
            raise PermissionError('untrusted signer ancestor')


def private_bytes(path, size=4096):
    path = Path(path)
    trusted(path.parent)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid() or
                before.st_mode & 0o077 or before.st_size > size):
            raise PermissionError('private signer file required')
        data = os.read(fd, size + 1)
        after = os.fstat(fd)
        if (len(data) != before.st_size or len(data) > size or
                (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) !=
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) or
                (path.lstat().st_dev, path.lstat().st_ino) != (before.st_dev, before.st_ino)):
            raise ValueError('signer file changed')
        return data
    finally:
        os.close(fd)


@dataclass(frozen=True)
class Scope:
    repo: str
    task_issue: int
    body_digest: str
    authority_identity: str
    runner_commit: str
    start: str
    cursors: dict
    app_id: int

    def __post_init__(self):
        if (self.repo != REPO or self.task_issue != 43 or
                not isinstance(self.body_digest, str) or not HEX64.fullmatch(self.body_digest) or
                not isinstance(self.authority_identity, str) or not HEX64.fullmatch(self.authority_identity) or
                not isinstance(self.runner_commit, str) or not HEX40.fullmatch(self.runner_commit) or
                not isinstance(self.start, str) or not UTC.fullmatch(self.start) or
                type(self.app_id) is not int or self.app_id != 1144995 or
                not isinstance(self.cursors, dict) or set(self.cursors) != {'41', '45'} or
                any(type(v) is not int or v < 0 for v in self.cursors.values())):
            raise ValueError('signer scope not the frozen task')


def load_scope(path):
    value = json.loads(private_bytes(path))
    if not isinstance(value, dict) or set(value) != set(Scope.__dataclass_fields__):
        raise ValueError('signer scope schema')
    return Scope(**value)


class RateLimited(Exception):
    pass

def remaining(deadline, cap):
    if deadline is None:
        return cap
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise TimeoutError('signer overall deadline')
    return min(cap, seconds)


class GitHub:
    """Bounded exact GET and issue-comment POST with a separate root-only token."""
    def __init__(self, token_path, *, deadline=None):
        token = private_bytes(token_path)
        if not token or len(token) > 1024 or b'\n' in token or b'\r' in token:
            raise ValueError('signer token malformed')
        self._token = token.decode('ascii')
        self.deadline = deadline

    def _request(self, method, path, body=None):
        prefix = f'/repos/{REPO}/'
        readback = re.fullmatch(
            r'(?:git/ref/heads/(?:main|issue43-one-shot-review-note)|pulls\?state=open&head=aliercankonus%3Aissue43-one-shot-review-note&per_page=2|compare/[0-9a-f]{40}\.\.\.[0-9a-f]{40}|commits/[0-9a-f]{40}/(?:check-runs\?per_page=100|status)|actions/runs\?head_sha=[0-9a-f]{40}&per_page=100|issues/43/comments\?per_page=100&page=[1-5])',
            path[len(prefix):]) if path.startswith(prefix) else None
        regular = path.startswith(prefix) and re.fullmatch(
                r'(?:issues/43|issues/comments/[1-9][0-9]*|issues/(?:41|45)/comments(?:\?[^?]*)?)',
                path[len(prefix):])
        if not ((method == 'GET' and path == '/user') or
                (method == 'GET' and (regular or readback)) or
                (method == 'POST' and regular)) or (method == 'POST' and
                not re.fullmatch(r'issues/(?:41|45)/comments', path[len(prefix):])) or method not in ('GET', 'POST'):
            raise ValueError('signer request outside fixed scope')
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                raise RuntimeError('redirect denied')
        req = urllib.request.Request('https://api.github.com' + path,
            data=canonical(body) if body is not None else None, method=method,
            headers={'Authorization': 'Bearer ' + self._token,
                     'Accept': 'application/vnd.github+json',
                     'Content-Type': 'application/json', 'User-Agent': 'signal-desk-root-signer'})
        # Socket timeouts are inactivity bounds, not whole-response bounds: a
        # drip-fed response could otherwise keep a signer request alive forever.
        limit = remaining(self.deadline, 12)
        old_handler = signal.getsignal(signal.SIGALRM)
        old_timer = signal.getitimer(signal.ITIMER_REAL)
        if old_timer[0]:
            raise RuntimeError('pre-existing alarm cannot be replaced safely')
        def alarm(_signal, _frame):
            raise TimeoutError('signer request deadline')
        signal.signal(signal.SIGALRM, alarm)
        signal.setitimer(signal.ITIMER_REAL, limit)
        try:
            try:
                with urllib.request.build_opener(NoRedirect).open(req, timeout=limit) as response:
                    raw = response.read(65537)
                    if len(raw) > 65536:
                        raise ValueError('signer response too large')
                    remaining(self.deadline, 12)
                    return json.loads(raw)
            except urllib.error.HTTPError as exc:
                if exc.code in (403, 429):
                    raise RateLimited() from None
                raise RuntimeError('signer GitHub request failed') from None
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, old_handler)

    def task(self, issue):
        if issue != 43:
            raise ValueError('wrong task')
        return self._request('GET', f'/repos/{REPO}/issues/43')

    def get(self, path):
        return self._request('GET', path)

    def comment(self, issue, comment_id):
        if issue not in ISSUES or type(comment_id) is not int or comment_id < 1:
            raise ValueError('wrong comment')
        return self._request('GET', f'/repos/{REPO}/issues/comments/{comment_id}')

    def publish(self, issue, body):
        if issue not in ISSUES or len(body.encode()) > 2048:
            raise ValueError('grant outside bounds')
        result = self._request('POST', f'/repos/{REPO}/issues/{issue}/comments', {'body': body})
        if type(result.get('id')) is not int or result['id'] < 1:
            raise ValueError('grant response invalid')
        return result['id']

    def candidates(self, issue, start, *, deadline=None):
        if issue not in ISSUES or not UTC.fullmatch(start):
            raise ValueError('signer feed outside scope')
        # The root signer has no unbounded historical scan or webhook trust.
        from urllib.parse import urlencode
        for page in range(1, 6):
            remaining(deadline if deadline is not None else self.deadline, 12)
            query = urlencode({'per_page': 100, 'page': page, 'since': start})
            rows = self._request('GET', f'/repos/{REPO}/issues/{issue}/comments?{query}')
            if not isinstance(rows, list) or len(rows) > 100:
                raise ValueError('signer feed invalid')
            yield from rows
            if len(rows) < 100:
                return
        raise ValueError('signer feed exceeds bound')


def instruction(scope, issue, comment_id, row):
    if (issue not in ISSUES or type(comment_id) is not int or
            comment_id <= scope.cursors[str(issue)] or not isinstance(row, dict) or
            row.get('id') != comment_id or
            row.get('issue_url') != f'https://api.github.com/repos/{REPO}/issues/{issue}' or
            not isinstance(row.get('created_at'), str) or not UTC.fullmatch(row['created_at']) or
            row['created_at'] != row.get('updated_at') or row['created_at'] < scope.start or
            not isinstance(row.get('performed_via_github_app'), dict) or
            row['performed_via_github_app'].get('id') != scope.app_id or
            row.get('body') != f'RUN FROZEN DEVELOPMENT TASK #43 AUTH {scope.authority_identity}'):
        raise ValueError('instruction failed frozen scope or App provenance')
    return hashlib.sha256(row['body'].encode('utf-8')).hexdigest()


class Claim:
    """Fresh one-way private journal. An existing claim is always NO-REPLAY."""
    def __init__(self, root, comment_id):
        self.root = Path(root)
        self.directory = self.root / str(comment_id)
        self.file = self.directory / 'state.json'

    def save(self, record, *, first=False):
        data = canonical(record)
        if len(data) > MAX_STATE:
            raise ValueError('signer journal oversized')
        trusted(self.root)
        if first:
            self.directory.mkdir(mode=0o700)
        info = self.directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise PermissionError('signer claim not private')
        if not first:
            private_bytes(self.file, MAX_STATE)
        tmp = self.directory / ('state-' + os.urandom(8).hex())
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as out:
            out.write(data); out.flush(); os.fsync(out.fileno())
        if first:
            os.link(tmp, self.file, follow_symlinks=False)
            tmp.unlink()
        else:
            os.replace(tmp, self.file)
        dirfd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
        if first:
            parent = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(parent)
            finally:
                os.close(parent)


def sign_once(scope, state_root, client, issue, comment_id, sign, *, verify=None, deadline=None):
    """Exact GET fences -> claim -> sign -> POST intent -> one POST -> GET receipt."""
    if issue not in ISSUES or type(comment_id) is not int or comment_id <= scope.cursors[str(issue)]:
        raise ValueError('instruction before enrollment cursor')
    claim = Claim(state_root, comment_id)
    if claim.directory.exists() or claim.directory.is_symlink():
        raise FileExistsError('instruction already claimed; reconcile read-only')
    remaining(deadline, 12)
    task = client.task(scope.task_issue)
    if (not isinstance(task, dict) or task.get('number') != scope.task_issue or
            task.get('state') != 'open' or not isinstance(task.get('body'), str) or
            hashlib.sha256(task['body'].encode('utf-8')).hexdigest() != scope.body_digest):
        raise ValueError('frozen task changed')
    remaining(deadline, 12)
    first = client.comment(issue, comment_id)
    digest = instruction(scope, issue, comment_id, first)
    claim.save({'phase': 'claimed', 'issue': issue, 'instruction_id': comment_id,
                'instruction_sha256': digest}, first=True)
    remaining(deadline, 12)
    fresh = client.comment(issue, comment_id)
    if fresh != first or instruction(scope, issue, comment_id, fresh) != digest:
        raise ValueError('instruction changed after claim')
    remaining(deadline, 12)
    again = client.task(scope.task_issue)
    if again != task:
        raise ValueError('task changed before signature')
    payload = {'v': 1, 'repo': REPO, 'issue': issue, 'instruction_id': comment_id,
               'instruction_sha256': digest, 'task_issue': scope.task_issue,
               'authority_identity': scope.authority_identity,
               'runner_commit': scope.runner_commit, 'scope': 'development-only'}
    remaining(deadline, 10)
    signature = sign(canonical(payload)) if deadline is None else sign(canonical(payload), deadline=deadline)
    remaining(deadline, 10)
    valid = (verify(canonical(payload), signature) if deadline is None else
             verify(canonical(payload), signature, deadline=deadline)) if verify is not None else False
    if not isinstance(signature, bytes) or len(signature) != 64 or verify is None or not valid:
        raise ValueError('signer/public verifier mismatch')
    envelope = {'signal_desk_grant_v1': {'payload': payload,
                'signature': base64.b64encode(signature).decode('ascii')}}
    text = canonical(envelope).decode('ascii')
    claim.save({'phase': 'post-intent', 'issue': issue, 'instruction_id': comment_id,
                'instruction_sha256': digest, 'grant_sha256': hashlib.sha256(text.encode()).hexdigest()})
    remaining(deadline, 12)
    grant_id = client.publish(issue, text)
    remaining(deadline, 12)
    receipt = client.comment(issue, grant_id)
    if (not isinstance(receipt, dict) or receipt.get('id') != grant_id or grant_id <= comment_id or
            receipt.get('issue_url') != f'https://api.github.com/repos/{REPO}/issues/{issue}' or
            receipt.get('body') != text or receipt.get('created_at') != receipt.get('updated_at')):
        raise ValueError('grant receipt changed; reconcile only')
    result = {'phase': 'verified', 'issue': issue, 'instruction_id': comment_id,
              'instruction_sha256': digest, 'grant_sha256': hashlib.sha256(text.encode()).hexdigest(),
              'grant_id': grant_id}
    claim.save(result)
    return {'status': 'verified', 'grant_id': grant_id}


def sign_scan(scope, state_root, client, sign, *, verify, deadline=None):
    """One bounded scan; no polling, no model and no signature for empty feeds."""
    for issue in ISSUES:
        remaining(deadline, 12)
        rows = client.candidates(issue, scope.start) if deadline is None else client.candidates(issue, scope.start, deadline=deadline)
        for row in rows:
            remaining(deadline, 12)
            comment_id = row.get('id') if isinstance(row, dict) else None
            if type(comment_id) is not int or comment_id <= scope.cursors[str(issue)]:
                continue
            if row.get('body') != f'RUN FROZEN DEVELOPMENT TASK #43 AUTH {scope.authority_identity}':
                continue
            return sign_once(scope, state_root, client, issue, comment_id, sign, verify=verify, deadline=deadline)
    return None


def openssl_sign(key_path, payload, *, deadline=None):
    """Sign only after private key preflight; no shell and no key in argv/stdout."""
    private_bytes(key_path, 8192)
    with tempfile.TemporaryDirectory(dir=Path(key_path).parent) as directory:
        message = Path(directory) / 'payload'
        message.write_bytes(payload)
        result = subprocess.run(['openssl', 'pkeyutl', '-sign', '-inkey', str(key_path),
                                 '-rawin', '-in', str(message)], capture_output=True,
                                timeout=remaining(deadline, 10), check=True)
        if len(result.stdout) != 64:
            raise ValueError('invalid Ed25519 signature')
        return result.stdout


def openssl_verify(public_path, payload, signature, *, deadline=None):
    public = private_bytes(public_path, 8192)
    with tempfile.TemporaryDirectory(dir=Path(public_path).parent) as directory:
        key = Path(directory) / 'public.pem'; key.write_bytes(public)
        msg = Path(directory) / 'payload'; msg.write_bytes(payload)
        sig = Path(directory) / 'signature'; sig.write_bytes(signature)
        return subprocess.run(['openssl', 'pkeyutl', '-verify', '-pubin', '-inkey',
                               str(key), '-rawin', '-in', str(msg), '-sigfile', str(sig)],
                              capture_output=True, timeout=remaining(deadline, 10)).returncode == 0
