"""Dormant, one-shot, issue-scoped GitHub inbox. No model call on polling.

Only a separately signed grant for a previously posted immutable instruction
can claim the one enrolled Bridge task. Never invoke this module from a child.
"""
from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

from queue_store import TaskStore, _trusted_ancestors
from bridge_queue import BridgeQueue, _revision
from signal_desk.task_bridge.bridge import REPO, load_authorization
from signal_desk.task_bridge.context import load_execution_context

ISSUES = (41, 45)
MAX_PAGES = 5
MAX_BODY = 8192


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')


def private_file(path, limit):
    path = Path(path)
    _trusted_ancestors(path.parent)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid() or
                before.st_mode & 0o077 or before.st_size > limit):
            raise PermissionError('private bounded regular file required')
        content = os.read(fd, limit + 1)
        after = os.fstat(fd)
        named = path.lstat()
        if (len(content) != before.st_size or before.st_size > limit or
            (before.st_dev, before.st_ino, before.st_mtime_ns, before.st_size) !=
            (after.st_dev, after.st_ino, after.st_mtime_ns, after.st_size) or
            (named.st_dev, named.st_ino) != (before.st_dev, before.st_ino)):
            raise ValueError('private file changed during read')
        return content
    finally:
        os.close(fd)


def load_enrollment(path):
    record = json.loads(private_file(path, 4096))
    expected = {'repo', 'issues', 'task_issue', 'runner', 'runner_commit', 'queue',
                'authorization', 'context', 'public_key', 'public_key_sha256', 'interval_seconds'}
    if (not isinstance(record, dict) or set(record) != expected or record['repo'] != REPO or
            record['issues'] != list(ISSUES) or type(record['task_issue']) is not int or
            record['task_issue'] in ISSUES or type(record['interval_seconds']) is not int or
            record['interval_seconds'] < 300 or
            not re.fullmatch('[0-9a-f]{40}', record['runner_commit']) or
            not re.fullmatch('[0-9a-f]{64}', record['public_key_sha256'])):
        raise ValueError('enrollment outside reviewed scope')
    for key in ('runner', 'queue', 'authorization', 'context', 'public_key'):
        p = Path(record[key])
        if not p.is_absolute() or '..' in p.parts or p.is_symlink():
            raise ValueError('absolute, unsymlinked enrollment paths required')
    key = private_file(record['public_key'], 4096)
    if hashlib.sha256(key).hexdigest() != record['public_key_sha256']:
        raise ValueError('manager verifier key changed')
    policy = load_authorization(record['authorization'])
    if policy.issue != record['task_issue'] or policy.repo != REPO:
        raise ValueError('enrolled task authorization mismatch')
    runner = Path(record['runner']).resolve(strict=True)
    if _revision(runner) != record['runner_commit']:
        raise ValueError('reviewed runner changed')
    context = load_execution_context(record['context'], runner, record['queue'])
    if context.runner_commit != record['runner_commit']:
        raise ValueError('private execution context changed')
    return record, policy, key


class RateLimited(Exception):
    def __init__(self, delay):
        self.delay = delay


class GitHub:
    """Bounded authenticated GET; only two issue feeds and exact comments."""
    def __init__(self):
        credential = subprocess.run(['git', 'credential', 'fill'],
            input='protocol=https\nhost=github.com\n\n', text=True,
            capture_output=True, check=True, timeout=10).stdout
        token = next((line[9:] for line in credential.splitlines()
                      if line.startswith('password=')), None)
        if not token:
            raise RuntimeError('GitHub credential absent')
        self.token = token

    def request(self, method, path, body=None, etag=None):
        prefix = '/repos/' + REPO + '/issues/'
        if not path.startswith(prefix) or not re.fullmatch(
            r'(?:41|45)(?:/comments(?:\?[^?]*)?)?|comments/[1-9][0-9]*', path[len(prefix):]):
            raise ValueError('GitHub inbox path outside issue allowlist')
        if method not in ('GET', 'POST') or (method == 'POST' and
                not re.fullmatch(r'(41|45)/comments', path[len(prefix):])):
            raise ValueError('GitHub inbox method outside allowlist')
        headers = {'Authorization': 'Bearer ' + self.token,
                   'Accept': 'application/vnd.github+json',
                   'Content-Type': 'application/json', 'User-Agent': 'signal-desk-bounded-inbox'}
        if etag:
            headers['If-None-Match'] = etag
        req = urllib.request.Request('https://api.github.com' + path,
            data=canonical(body) if body is not None else None, method=method, headers=headers)
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                raise RuntimeError('redirect denied')
        try:
            with urllib.request.build_opener(NoRedirect).open(req, timeout=15) as resp:
                data = resp.read(131073)
                if len(data) > 131072:
                    raise ValueError('GitHub response exceeds bound')
                return json.loads(data), resp.headers.get('ETag')
        except urllib.error.HTTPError as exc:
            if exc.code == 304:
                return None, etag
            if exc.code in (403, 429):
                retry = exc.headers.get('Retry-After')
                reset = exc.headers.get('X-RateLimit-Reset')
                delay = min(86400, max(300, int(retry))) if retry and retry.isdecimal() else (
                    min(86400, max(300, int(reset) - int(time.time())))
                    if reset and reset.isdecimal() else 300)
                raise RateLimited(delay) from None
            raise RuntimeError('GitHub request failed (HTTP ' + str(exc.code) + ')') from None

    def latest(self, issue):
        if issue not in ISSUES:
            raise ValueError('issue outside enrollment')
        item, _ = self.request('GET', f'/repos/{REPO}/issues/{issue}')
        if item is None or item.get('number') != issue or type(item.get('comments')) is not int:
            raise ValueError('issue comment count invalid')
        count = item['comments']
        if count == 0:
            return 0
        page = (count - 1) // 100 + 1
        rows, _ = self.request('GET', f'/repos/{REPO}/issues/{issue}/comments?per_page=100&page={page}')
        if not isinstance(rows, list) or not rows or len(rows) > 100:
            raise ValueError('latest comment page unavailable')
        latest = rows[-1].get('id')
        if type(latest) is not int or latest < 1:
            raise ValueError('latest comment ID invalid')
        return latest

    def comments(self, issue, since, etag=None):
        if issue not in ISSUES:
            raise ValueError('issue outside enrollment')
        first_etag = None
        for page in range(1, MAX_PAGES + 1):
            query = urllib.parse.urlencode({'per_page': 100, 'page': page, 'since': since})
            rows, tag = self.request('GET', f'/repos/{REPO}/issues/{issue}/comments?{query}',
                                     etag=etag if page == 1 else None)
            if page == 1:
                first_etag = tag
            if rows is None:
                return [], etag
            if not isinstance(rows, list) or len(rows) > 100:
                raise ValueError('invalid comment page')
            for row in rows:
                yield row, first_etag
            if len(rows) < 100:
                return
        raise ValueError('comment feed exceeds bounded pagination')

    def comment(self, issue, comment_id):
        if issue not in ISSUES or type(comment_id) is not int or comment_id < 1:
            raise ValueError('comment outside issue scope')
        row, _ = self.request('GET', f'/repos/{REPO}/issues/comments/{comment_id}')
        if row.get('id') != comment_id or row.get('issue_url') != f'https://api.github.com/repos/{REPO}/issues/{issue}':
            raise ValueError('comment identity mismatch')
        return row

    def publish(self, issue, text):
        if issue not in ISSUES or len(text) > 2048:
            raise ValueError('status outside bounds')
        posted, _ = self.request('POST', f'/repos/{REPO}/issues/{issue}/comments', {'body': text})
        receipt = self.comment(issue, posted['id'])
        if receipt.get('body') != text:
            raise ValueError('status readback mismatch')
        return receipt['id']


def verify_grant(grant, key, *, verifier=None):
    if not isinstance(grant, dict) or set(grant) != {'signal_desk_grant_v1'}:
        return None
    envelope = grant['signal_desk_grant_v1']
    if not isinstance(envelope, dict) or set(envelope) != {'payload', 'signature'}:
        return None
    payload = envelope['payload']
    fields = {'v', 'repo', 'issue', 'instruction_id', 'instruction_sha256',
              'task_issue', 'authority_identity', 'runner_commit', 'scope'}
    if not isinstance(payload, dict) or set(payload) != fields or not (
            payload['v'] == 1 and payload['repo'] == REPO and
            payload['issue'] in ISSUES and type(payload['instruction_id']) is int and
            payload['instruction_id'] > 0 and type(payload['task_issue']) is int and
            payload['scope'] == 'development-only' and
            all(isinstance(payload[k], str) and re.fullmatch(f'[0-9a-f]{{{n}}}', payload[k])
                for k, n in (('instruction_sha256', 64), ('authority_identity', 64),
                             ('runner_commit', 40)))):
        return None
    try:
        signature = base64.b64decode(envelope['signature'], validate=True)
    except (ValueError, TypeError):
        return None
    if len(signature) != 64:
        return None
    if verifier is None:
        verifier = openssl_verify
    if not verifier(key, canonical(payload), signature):
        return None
    return payload


def openssl_verify(public_key, payload, signature):
    # The public verifier is never a manager signing credential. No shell.
    with tempfile.TemporaryDirectory() as directory:
        key = Path(directory) / 'key.pem'
        sig = Path(directory) / 'signature'
        message = Path(directory) / 'payload'
        key.write_bytes(public_key)
        sig.write_bytes(signature)
        message.write_bytes(payload)
        result = subprocess.run(['openssl', 'pkeyutl', '-verify', '-pubin',
            '-inkey', str(key), '-rawin', '-in', str(message), '-sigfile', str(sig)],
            capture_output=True, timeout=10)
        return result.returncode == 0


class Inbox:
    def __init__(self, enrollment_path, state_root, github, executor, verifier=None):
        self.enrollment_path = Path(enrollment_path)
        self.root = Path(state_root)
        self.github = github
        self.executor = executor
        self.verifier = verifier

    def _config(self):
        config, policy, key = load_enrollment(self.enrollment_path)
        if self.root != Path(config['queue']).parent / 'github-inbox' or not self.root.is_absolute():
            raise ValueError('inbox root must be dedicated sibling of reviewed queue')
        return config, policy, key

    def _locked(self):
        _trusted_ancestors(self.root.parent)
        if self.root.is_symlink() or not self.root.is_dir():
            raise FileNotFoundError('enroll before polling; private state absent')
        info = self.root.lstat()
        if info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise PermissionError('inbox state not private')
        fd = os.open(self.root / 'inbox.lock', os.O_RDONLY | os.O_NOFOLLOW)
        info = os.fstat(fd)
        named = (self.root / 'inbox.lock').lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or
                info.st_mode & 0o077 or info.st_nlink != 1 or
                (info.st_dev, info.st_ino) != (named.st_dev, named.st_ino)):
            os.close(fd)
            raise PermissionError('inbox lock not private')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            os.close(fd)
            raise
        return fd

    def _read(self):
        return json.loads(private_file(self.root / 'state.json', 8192))

    def _save(self, state):
        data = canonical(state)
        if len(data) > 8192:
            raise ValueError('inbox state exceeds bound')
        name = self.root / ('state-' + os.urandom(8).hex())
        fd = os.open(name, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.root / 'state.json')
            dirfd = os.open(self.root, os.O_DIRECTORY | os.O_RDONLY | os.O_NOFOLLOW)
            try:
                os.fsync(dirfd)
            finally:
                os.close(dirfd)
        finally:
            name.unlink(missing_ok=True)

    def enroll(self, start):
        """Operator-only initial snapshot. Never scan historical grants as new work."""
        config, policy, key = self._config()
        if self.root.exists() or self.root.is_symlink():
            raise FileExistsError('enrollment already exists; do not reset cursor')
        if not isinstance(start, str) or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ', start):
            raise ValueError('explicit UTC enrollment timestamp required')
        cursors = {}
        for issue in ISSUES:
            # Old history can exceed bounds. Use caller-reviewed latest ID, not an implicit zero.
            latest = self.github.latest(issue)
            if type(latest) is not int or latest < 0:
                raise ValueError('latest issue cursor unavailable')
            cursors[str(issue)] = latest
        self.root.mkdir(mode=0o700)
        lock = os.open(self.root / 'inbox.lock', os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(lock)
        self._save({'v': 1, 'enabled': False, 'enrollment_sha256':
                    hashlib.sha256(private_file(self.enrollment_path, 4096)).hexdigest(),
                    'start': start, 'start_cursor': dict(cursors), 'cursor': cursors, 'etag': {},
                    'claim': None, 'next_poll': 0})

    def doctor(self):
        config, policy, key = self._config()
        fd = self._locked()
        try:
            state = self._read()
            self._validate(state)
            return {k: state[k] for k in ('enabled', 'cursor', 'claim', 'next_poll')}
        finally:
            os.close(fd)

    def _validate(self, state):
        if (state.get('v') != 1 or state.get('enrollment_sha256') !=
                hashlib.sha256(private_file(self.enrollment_path, 4096)).hexdigest() or
                state.get('cursor', {}).keys() != {'41', '45'} or
                state.get('start_cursor', {}).keys() != {'41', '45'} or
                any(type(n) is not int or n < 0 for n in state['start_cursor'].values()) or
                any(state['cursor'][k] < state['start_cursor'][k] for k in ('41', '45')) or
                any(type(n) is not int or n < 0 for n in state['cursor'].values()) or
                type(state.get('enabled')) is not bool or
                not isinstance(state.get('start'), str) or
                not isinstance(state.get('etag'), dict) or
                not isinstance(state.get('next_poll'), (int, float))):
            raise ValueError('inbox state/enrollment changed; reconciliation required')

    def enable(self):
        config, policy, _ = self._config()
        fd = self._locked()
        try:
            state = self._read()
            self._validate(state)
            if state['claim'] is not None or state['enabled']:
                raise ValueError('existing claim or enabled enrollment; no reset')
            if TaskStore(Path(config['queue']), create=False).all_tasks():
                raise ValueError('queue not empty; read-only reconciliation required')
            state['enabled'] = True
            self._save(state)
        finally:
            os.close(fd)

    def disable(self):
        fd = self._locked()
        try:
            state = self._read()
            self._validate(state)
            state['enabled'] = False
            self._save(state)
        finally:
            os.close(fd)

    def tick(self):
        config, policy, key = self._config()
        fd = self._locked()
        try:
            state = self._read()
            self._validate(state)
            if not state['enabled'] or state['claim'] is not None:
                return {'status': 'disabled' if not state['enabled'] else 'blocked',
                        'reason': 'existing claim' if state['claim'] else 'not enabled'}
            if time.time() < state['next_poll']:
                return {'status': 'waiting'}
            try:
                for issue in ISSUES:
                    cursor = state['cursor'][str(issue)]
                    feed = list(self.github.comments(issue, state['start'], state['etag'].get(str(issue))))
                    for row, tag in feed:
                        number = row.get('id')
                        if type(number) is not int or number < 1:
                            raise ValueError('comment ID invalid')
                        if number <= cursor:
                            continue
                        body = row.get('body')
                        payload = None
                        if (isinstance(body, str) and len(body.encode('utf-8')) <= MAX_BODY and
                                row.get('created_at') == row.get('updated_at')):
                            try:
                                payload = verify_grant(json.loads(body), key, verifier=self.verifier)
                            except (TypeError, ValueError):
                                pass
                        if payload is not None and (payload['issue'] == issue and
                                state['start_cursor'][str(issue)] < payload['instruction_id'] < number and
                                payload['task_issue'] == policy.issue and
                                payload['authority_identity'] == policy.identity and
                                payload['runner_commit'] == config['runner_commit']):
                            target = self.github.comment(issue, payload['instruction_id'])
                            instruction = target.get('body')
                            if (target.get('created_at') != target.get('updated_at') or
                                    target.get('created_at', '') < state['start'] or
                                    target.get('id') > number or
                                    not isinstance(instruction, str) or
                                    not instruction or len(instruction.encode()) > MAX_BODY or
                                    hashlib.sha256(instruction.encode()).hexdigest() !=
                                    payload['instruction_sha256'] or
                                    instruction != ('RUN FROZEN DEVELOPMENT TASK #'
                                                    + str(policy.issue) + ' AUTH ' + policy.identity)):
                                state['cursor'][str(issue)] = number
                                state['claim'] = {'issue': issue, 'grant_id': number,
                                    'instruction_id': payload['instruction_id'],
                                    'instruction_sha256': payload['instruction_sha256'],
                                    'authority_identity': policy.identity,
                                    'status': 'blocked', 'queue_id': None,
                                    'reason': 'signed instruction changed or outside frozen scope'}
                                self._save(state)
                                try:
                                    self._receipt(state, issue, state['claim'], 'blocked')
                                except Exception:
                                    pass
                                return {'status': 'blocked', 'claim': state['claim']}
                            # Persist claim before any status POST, enqueue or model call.
                            state['cursor'][str(issue)] = number
                            state['claim'] = {'issue': issue, 'grant_id': number,
                                'instruction_id': payload['instruction_id'],
                                'instruction_sha256': payload['instruction_sha256'],
                                'authority_identity': policy.identity,
                                'status': 'claimed', 'queue_id': None}
                            self._save(state)
                            claim = state['claim']
                            try:
                                self._receipt(state, issue, claim, 'ack')
                                self._receipt(state, issue, claim, 'running')
                                # Re-read exact instruction and frozen authority before effects.
                                fresh = self.github.comment(issue, payload['instruction_id'])
                                if fresh != target:
                                    raise ValueError('instruction changed before dispatch')
                                checked, current_policy, _ = self._config()
                                if current_policy.identity != policy.identity or checked != config:
                                    raise ValueError('enrollment changed before dispatch')
                                result = self.executor(config, policy)
                                if not isinstance(result, dict) or result.get('status') not in ('blocked', 'review-ready'):
                                    raise ValueError('executor result unknown')
                                claim['queue_id'] = result.get('id')
                                claim['status'] = result['status']
                                self._save(state)
                                self._receipt(state, issue, claim, result['status'], result)
                                return {'status': claim['status'], 'claim': claim}
                            except Exception:
                                claim['status'] = 'blocked'
                                self._save(state)
                                # A separate blocked receipt is safe to attempt once;
                                # an uncertain earlier receipt stays an intent for review.
                                if claim.get('publication_intent') != 'blocked':
                                    try:
                                        self._receipt(state, issue, claim, 'blocked')
                                    except Exception:
                                        pass
                                return {'status': 'blocked', 'claim': claim}
                        state['cursor'][str(issue)] = number
                        state['etag'].pop(str(issue), None)
                        self._save(state)
                    # Cache only a complete first page; later pages can mutate independently.
                    if feed and len(feed) < 100 and feed[0][1]:
                        state['etag'][str(issue)] = feed[0][1]
                    elif len(feed) >= 100:
                        state['etag'].pop(str(issue), None)
                    self._save(state)
                state['next_poll'] = time.time() + config['interval_seconds']
                self._save(state)
                return {'status': 'empty'}
            except RateLimited as exc:
                state['next_poll'] = time.time() + exc.delay
                self._save(state)
                return {'status': 'rate-limited', 'reset': 'unknown' if exc.delay == 300 else 'header-delay'}
        finally:
            os.close(fd)

    def _receipt(self, state, issue, claim, status, result=None):
        item = {'inbox': 'issue45-v1', 'status': status, 'grant_id': claim['grant_id'],
                'instruction_id': claim['instruction_id'], 'queue_id': claim['queue_id']}
        if result:
            item['ci'] = result.get('ci')
        text = canonical(item).decode('ascii')
        claim['publication_intent'] = status
        self._save(state)
        receipt = self.github.publish(issue, text)
        claim.setdefault('receipts', []).append({'status': status, 'id': receipt})
        claim['publication_intent'] = None
        self._save(state)
        return receipt


def production_executor(config, policy):
    """Exactly the reviewed queue -> Bridge owner; no legacy execute_task."""
    queue = BridgeQueue(TaskStore(Path(config['queue']), create=False))
    if queue.store.all_tasks():
        raise ValueError('nonempty queue requires read-only reconciliation')
    entry = queue.enqueue(Path(config['runner']), Path(config['authorization']),
                          Path(config['context']), runner_commit=config['runner_commit'])
    result = queue.dispatch_one(BridgeQueue.production_bridge)
    if result.get('id') != entry['id']:
        raise ValueError('queue/Bridge result mapping changed')
    return result
