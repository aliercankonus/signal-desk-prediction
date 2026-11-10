#!/usr/bin/env python3
"""Dormant v2 root-only one-entry operator adapter; review does not install or run it.

Execution requires separately verified root/source/key/App/worker isolation and
operator authorization. A draft or an approval flag is NOT evidence of those.
No automatic restart, retry, cleanup of unknown IDs or second task dispatch.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import select
import shutil
import signal
import stat
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'github_inbox'))
from operator_lifecycle import Journal, Owned, run_once

REPO = 'aliercankonus/signal-desk-prediction'
RUNNER_PIN = 'e84021a786004456a12de9e25eae50d191da6cf1'
ARTIFACTS = {
    'ops/bridge_one_shot/bridge_readback.py',
    'ops/bridge_one_shot/operator_artifacts_v2.json',
    'ops/bridge_one_shot/operator_host_v2.py',
    'ops/bridge_one_shot/operator_lifecycle.py',
    'ops/bridge_one_shot/compose.operator.v2.yml',
    'ops/bridge_one_shot/connect_proxy.py',
    'ops/bridge_one_shot/network_preflight.py',
    'ops/bridge_one_shot/network_resources.py',
    'ops/bridge_one_shot/worker_firewall.sh',
    'ops/github_inbox/root_signer.py',
    'ops/github_inbox/worker_probe.py',
    'ops/github_inbox/worker_credential.py',
    'ops/github_inbox/worker_preflight.py',
}
HEX = re.compile(r'[0-9a-f]{64}\Z')
ATTEMPT = re.compile(r'[a-z][a-z0-9-]{5,63}\Z')
SIGNER_STATE_ROOT = Path('/var/lib/signal-desk/issue41-signer-claims')
CLEANUP_RESERVE = 420  # Worst-case bounded remote readback, ID cleanup and reporting.
SCAN_RESERVE = 120  # A bounded signer scan can consume several HTTP timeouts.
HOST_PATH = '/usr/sbin:/sbin:/usr/bin:/bin'


def require_host_tools():
    """Fail before any isolation effect if a required host executable is absent."""
    for tool in ('iptables', 'ip', 'docker', 'git', 'python3', 'bash', 'wc'):
        if shutil.which(tool, path=HOST_PATH) is None:
            raise FileNotFoundError(f'required host tool unavailable: {tool}')


@dataclass(frozen=True)
class Plan:
    attempt: str
    bundle: Path
    source: Path  # Root-protected Git object store for the approved merge.
    merge: str
    image: str
    uid: int
    gid: int
    runner: Path
    state: Path
    auth: Path
    context: Path
    home: Path
    venv: Path
    inbox: Path
    signer_token: Path
    signer_key: Path
    signer_public: Path
    signer_policy: Path
    signer_state_root: Path  # Root-only, durable across all attempts; never per-attempt.
    overall_seconds: int
    journal_parent: Path

    def __post_init__(self):
        if (not isinstance(self.attempt, str) or not ATTEMPT.fullmatch(self.attempt) or
                not isinstance(self.merge, str) or not re.fullmatch('[0-9a-f]{40}', self.merge) or
                not isinstance(self.image, str) or not re.fullmatch('sha256:[0-9a-f]{64}', self.image) or
                type(self.uid) is not int or self.uid < 1 or type(self.gid) is not int or self.gid < 1 or
                type(self.overall_seconds) is not int or not 600 <= self.overall_seconds <= 7200 or
                self.signer_state_root != SIGNER_STATE_ROOT or
                any(not isinstance(getattr(self, f.name), Path) or
                    not getattr(self, f.name).is_absolute() or '..' in getattr(self, f.name).parts
                    for f in fields(self) if f.type is Path or f.name in
                    {'bundle', 'source', 'runner', 'state', 'auth', 'context', 'home',
                     'venv', 'inbox', 'signer_token', 'signer_key', 'signer_public',
                     'signer_policy', 'signer_state_root', 'journal_parent'})):
            raise ValueError('unreviewed operator plan')


def load_plan(path):
    # Import only protected root-side code, not from the worker's writable runner.
    from root_signer import private_bytes
    value = json.loads(private_bytes(path, 8192))
    if not isinstance(value, dict) or set(value) != {f.name for f in fields(Plan)}:
        raise ValueError('operator plan schema')
    for key in ('bundle', 'source', 'runner', 'state', 'auth', 'context', 'home',
                'venv', 'inbox', 'signer_token', 'signer_key', 'signer_public',
                'signer_policy', 'signer_state_root', 'journal_parent'):
        value[key] = Path(value[key])
    return Plan(**value)


def trusted_worker_mount(path: Path, uid: int):
    path = Path(path)
    for ancestor in (path, *path.parents):
        info = ancestor.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, uid) or
                info.st_mode & 0o022):
            raise PermissionError('worker mount ancestor unsafe')
        if ancestor == path and info.st_mode & 0o077:
            raise PermissionError('worker mount not private to reviewed UID')


def worker_private_bytes(path: Path, uid: int, limit=4096):
    trusted_worker_mount(path.parent, uid)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid not in (0, uid) or
                info.st_mode & 0o077 or info.st_size > limit):
            raise PermissionError('worker private file outside reviewed owner/mode')
        content = os.read(fd, limit + 1)
        after = os.fstat(fd)
        named = path.lstat()
        if (len(content) != info.st_size or len(content) > limit or
                (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) !=
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) or
                (named.st_dev, named.st_ino) != (info.st_dev, info.st_ino)):
            raise ValueError('worker private file changed')
        return content
    finally:
        os.close(fd)


def protected_locations(p):
    # The common root-private workspace is not a mounted credential directory.
    # Test actual protected objects against exact worker bind sources, including
    # ancestor/descendant exposure. Never relax ownership or Git safety checks.
    return (p.bundle, p.source, p.signer_state_root, p.journal_parent,
            p.signer_token, p.signer_key, p.signer_public, p.signer_policy)


def check_signer_binding(plan: Plan, scope):
    from root_signer import private_bytes
    policy = json.loads(worker_private_bytes(plan.auth / 'authorization.json', plan.uid))
    if (not isinstance(policy, dict) or set(policy) !=
            {'repo', 'issue', 'body_digest', 'base', 'branch'} or
            policy['repo'] != REPO or policy['issue'] != 43 or
            policy['body_digest'] != scope.body_digest or policy['base'] != RUNNER_PIN or
            policy['branch'] != 'issue43-one-shot-review-note' or
            hashlib.sha256(json.dumps(policy, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            != scope.authority_identity):
        raise ValueError('private worker authorization differs from root scope')
    enrollment = json.loads(worker_private_bytes(plan.inbox / 'enrollment.json', plan.uid))
    public = private_bytes(plan.signer_public, 8192)
    worker_public = worker_private_bytes(plan.inbox / 'manager-public.pem', plan.uid, 8192)
    if (not isinstance(enrollment, dict) or enrollment.get('repo') != REPO or
            enrollment.get('issues') != [41, 45] or enrollment.get('task_issue') != 43 or
            enrollment.get('runner_commit') != RUNNER_PIN or
            enrollment.get('runner') != '/workspace/runner' or
            enrollment.get('queue') != '/state/queue' or
            enrollment.get('public_key') != '/private/inbox/manager-public.pem' or
            enrollment.get('authorization') != '/private/auth/authorization.json' or
            public != worker_public or
            enrollment.get('public_key_sha256') != hashlib.sha256(public).hexdigest()):
        raise ValueError('worker public verifier/enrollment differs from root scope')


class CommandRunner:
    """One bounded, no-shell process; stderr/stdout retained only in memory."""
    def __init__(self, *, deadline):
        self.deadline = deadline

    def __call__(self, argv, *, timeout, env=None, input=None):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('operator overall deadline')
        if not argv or any(not isinstance(arg, str) for arg in argv):
            raise ValueError('command argv invalid')
        safe_env = {'PATH': HOST_PATH, 'HOME': '/root', 'LC_ALL': 'C',
                    'GIT_CONFIG_NOSYSTEM': '1', 'GIT_TERMINAL_PROMPT': '0'}
        if env:
            safe_env.update(env)
        safe_env['PATH'] = HOST_PATH  # Caller fields may not redirect root executable lookup.
        completed = subprocess.run(argv, input=input, capture_output=True, check=True,
                                   timeout=min(float(timeout), remaining), env=safe_env)
        if len(completed.stdout) > 65536 or len(completed.stderr) > 65536:
            raise ValueError('bounded command output exceeded')
        return completed.stdout.decode('utf-8')


class HostOperations:
    """Only one future approved attempt; command seam is fully injectable offline."""
    def __init__(self, plan: Plan, *, runner, github=None, signer=None, pause=None, deadline=None):
        self.plan = plan
        self.runner = runner
        self.github = github
        self.signer = signer
        self.pause = pause or self._device_handoff
        self.deadline = deadline if deadline is not None else time.monotonic() + plan.overall_seconds
        self.baseline = None
        self.worker_id = None
        self.proxy_id = None
        self.network_ids = {}
        self.enrollment_inode = None
        self.claim_status = None
        self.report_text = None
        self.remote_result = None
        self.runtime_stopped = False  # True only after exact worker stop/readback.

    def _call(self, argv, timeout=20, *, env=None, input=None):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('operator overall deadline')
        return self.runner([str(item) for item in argv], timeout=min(timeout, remaining),
                           env=env, input=input)

    def _env(self):
        p = self.plan
        return {'HERMES_IMAGE_REF': p.image, 'HERMES_UID': str(p.uid), 'HERMES_GID': str(p.gid),
                'SD_ATTEMPT_ID': p.attempt, 'BRIDGE_RUNNER_HOST': str(p.runner),
                'BRIDGE_STATE_PARENT_HOST': str(p.state), 'BRIDGE_AUTH_DIR_HOST': str(p.auth),
                'BRIDGE_CONTEXT_DIR_HOST': str(p.context), 'BRIDGE_HOME_HOST': str(p.home),
                'BRIDGE_VENV_HOST': str(p.venv), 'BRIDGE_INBOX_CONFIG_HOST': str(p.inbox),
                'BRIDGE_REVIEW_HOST': str(p.bundle)}

    def _compose(self, *args, timeout=45):
        return self._call(['docker', 'compose', '--env-file', '/dev/null',
                           '-f', self.plan.bundle / 'compose.operator.v2.yml',
                           '--profile', 'execution', *args], timeout, env=self._env())

    def _docker(self, *args, timeout=20):
        return self._call(['docker', *args], timeout)

    def _service(self, name):
        ident = self._compose('ps', '-q', name, timeout=15).strip()
        if not HEX.fullmatch(ident):
            raise ValueError('service identity unknown')
        return ident

    def _container(self, ident, service, *, running=None):
        if not isinstance(ident, str) or not HEX.fullmatch(ident):
            raise ValueError('container identity invalid')
        raw = self._docker('inspect', '--type', 'container', '--format', '{{json .}}', ident)
        item = json.loads(raw)
        labels = (item.get('Config') or {}).get('Labels') or {}
        if (item.get('Id') != ident or item.get('Image') != self.plan.image or
                labels.get('org.signal-desk.issue41.attempt') != self.plan.attempt or
                labels.get('com.docker.compose.project') != 'signal-desk-bridge-once' or
                labels.get('com.docker.compose.service') != service or
                (running is not None and (item.get('State') or {}).get('Running') is not running)):
            raise ValueError('container identity/image/label mismatch')
        return item

    def _network(self, role, *, proxy=None):
        ident = self.network_ids.get(role)
        if not ident or not HEX.fullmatch(ident):
            raise ValueError('network ID not recorded')
        record = self._docker('network', 'inspect', ident)
        item = json.loads(record)
        if (not isinstance(item, list) or len(item) != 1 or
                (item[0].get('Labels') or {}).get('org.signal-desk.issue41.attempt') != self.plan.attempt):
            raise ValueError('network attempt label mismatch')
        argv = ['python3', '-I', '-B', self.plan.bundle / 'network_resources.py', '--role', role]
        if proxy is not None:
            argv += ['--proxy-id', proxy]
        if self._call(argv, input=record.encode()).strip() != ident:
            raise ValueError('network helper identity mismatch')

    def merged_blob(self, name):
        if name not in ARTIFACTS:
            raise ValueError('merged blob outside approved inventory')
        spec = self.plan.merge + ':' + name
        size = self._call(['git', '--git-dir=' + str(self.plan.source), 'cat-file', '-s', spec]).strip()
        if not size.isascii() or not size.isdecimal() or int(size) > 65536:
            raise ValueError('merged blob size outside 64 KiB')
        blob = self._call(['git', '--git-dir=' + str(self.plan.source), 'show', spec])
        if len(blob.encode('utf-8')) != int(size):
            raise ValueError('merged blob size changed')
        return blob

    def preflight(self):
        from root_signer import private_bytes, trusted, load_scope
        p = self.plan
        if os.geteuid() != 0:
            raise PermissionError('root operator required')
        require_host_tools()
        for path in (p.bundle, p.source, p.journal_parent, p.signer_state_root,
                     p.signer_token.parent, p.signer_key.parent, p.signer_policy.parent):
            trusted(path)
        for path in (p.bundle, p.source, p.journal_parent, p.signer_state_root):
            info = path.lstat()
            if info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o700:
                raise PermissionError('root executable and durable state must be private 0700')
        for path in (p.runner, p.state, p.auth, p.context, p.home, p.venv, p.inbox):
            trusted_worker_mount(path, p.uid)
        queue_path = p.state / 'queue'
        trusted_worker_mount(queue_path, p.uid)
        if any(queue_path.iterdir()):
            raise ValueError('dedicated queue is not empty')
        for candidate in (p.signer_token, p.signer_key, p.signer_public, p.signer_policy):
            private_bytes(candidate, 8192)
        scope = load_scope(p.signer_policy)
        if scope.runner_commit != RUNNER_PIN:
            raise ValueError('private signer scope uses another runner')
        check_signer_binding(p, scope)
        for location in protected_locations(p):
            for mount in (p.runner, p.state, p.auth, p.context, p.home, p.venv, p.inbox):
                if location == mount or location in mount.parents or mount in location.parents:
                    raise PermissionError('root signer/bundle overlaps worker mount')
        if self._call(['git', '--git-dir=' + str(p.source), 'cat-file', '-t', p.merge]).strip() != 'commit':
            raise ValueError('merge object absent')
        inventory = json.loads(private_bytes(p.bundle / 'operator_artifacts_v2.json', 4096))
        merged = json.loads(private_bytes(p.bundle / 'merged-byte-manifest.json', 4096))
        if (inventory.get('schema') != 2 or inventory.get('runner_commit') != RUNNER_PIN or
                set(inventory.get('files', [])) != ARTIFACTS or
                merged.get('schema') != 1 or merged.get('merge') != p.merge or
                set(merged.get('sha256', {})) != ARTIFACTS):
            raise ValueError('merged artifact inventory incomplete or mismatched')
        if {file.name for file in p.bundle.iterdir()} != (
                {Path(name).name for name in ARTIFACTS} | {'merged-byte-manifest.json'}):
            raise ValueError('unexpected staged helper file')
        for name in sorted(ARTIFACTS):
            blob = self.merged_blob(name)
            local = p.bundle / Path(name).name
            mode = 0o444 if local.name in {'worker_probe.py', 'connect_proxy.py', 'worker_credential.py', 'worker_preflight.py'} else 0o600
            if (local.is_symlink() or not local.is_file() or local.stat().st_uid != 0 or
                    stat.S_IMODE(local.stat().st_mode) != mode or local.stat().st_size > 65536 or
                    hashlib.sha256(local.read_bytes()).digest() != hashlib.sha256(blob.encode()).digest() or
                    merged['sha256'][name] != hashlib.sha256(blob.encode()).hexdigest()):
                raise ValueError('staged bytes differ from approved merge')
        if self._docker('image', 'inspect', '--format', '{{.Id}}', p.image).strip() != p.image:
            raise ValueError('image ID changed')
        self._compose('config', '-q')
        self._call(['python3', '-I', '-B', p.bundle / 'network_preflight.py'], timeout=30)
        existing = self._docker('ps', '-aq', '--no-trunc', '--filter',
                                'label=com.docker.compose.project=signal-desk-bridge-once').strip()
        nets = self._docker('network', 'ls', '-q', '--no-trunc', '--filter',
                            'label=com.docker.compose.project=signal-desk-bridge-once').strip()
        if existing or nets:
            raise ValueError('attempt resources already exist')
        rules = self._call(['iptables', '-S'], timeout=15)
        if 'SD_ONCE_IN' in rules or 'SD_ONCE_FWD' in rules:
            raise ValueError('firewall chain already present')
        self.baseline = (self._docker('ps', '-aq', '--no-trunc'),
                         self._docker('network', 'ls', '-q', '--no-trunc'))
        if (p.state / 'github-inbox').exists() or (p.state / 'github-inbox').is_symlink():
            raise FileExistsError('existing inbox state; never reset cursor')

    def start_isolation(self):
        # Intent is fsynced by run_once BEFORE this first Compose effect.
        self._compose('up', '-d', '--no-deps', '--no-recreate', '--no-build',
                      '--pull', 'never', 'connect-proxy', timeout=60)
        self.proxy_id = self._service('connect-proxy')
        self._container(self.proxy_id, 'connect-proxy', running=True)
        for role in ('worker_isolated', 'proxy_uplink'):
            result = self._docker('network', 'ls', '-q', '--no-trunc',
                                  '--filter', 'label=com.docker.compose.project=signal-desk-bridge-once',
                                  '--filter', 'label=com.docker.compose.network=' + role).strip()
            if not HEX.fullmatch(result):
                raise ValueError('network identity unknown after startup')
            self.network_ids[role] = result
            self._network(role, proxy=self.proxy_id)
        env = {'AUTODEV_FIREWALL_APPROVED': 'yes-for-reviewed-network'}
        self._call(['bash', self.plan.bundle / 'worker_firewall.sh', 'apply'], timeout=35, env=env)
        self._call(['bash', self.plan.bundle / 'worker_firewall.sh', 'status'], timeout=20)
        self._compose('up', '-d', '--no-deps', '--no-recreate', '--no-build',
                      '--pull', 'never', 'inbox-worker', timeout=60)
        self.worker_id = self._service('inbox-worker')
        self._container(self.worker_id, 'inbox-worker', running=True)
        return tuple(Owned(kind, ident, self.plan.attempt) for kind, ident in (
            ('network', self.network_ids['worker_isolated']),
            ('network', self.network_ids['proxy_uplink']),
            ('proxy', self.proxy_id), ('firewall', 'SD_ONCE_IN'), ('worker', self.worker_id)))

    def _worker(self, *args, timeout=30):
        if self.worker_id is None:
            raise ValueError('worker identity unrecorded')
        self._container(self.worker_id, 'inbox-worker', running=True)
        return self._docker('exec', self.worker_id, *args, timeout=timeout)

    def _device_handoff(self, worker_id, seconds):
        if not sys.stdin.isatty() or seconds <= 0:
            raise TimeoutError('device-login handoff requires a live root operator terminal')
        # An operator performs login in a second terminal, in this exact worker.
        # Do NOT enter a token/password/code into the journal or this prompt.
        print('STOP for bounded device login in the isolated worker ID:', worker_id)
        print('Use only the independently approved provider device flow in the dedicated home;')
        print('GitHub uses the separately prepared read-only credential helper; no gh login.')
        print('type DONE here only after private login, or let the handoff expire.')
        ready, _, _ = select.select([sys.stdin], [], [], min(seconds, 600))
        if not ready or sys.stdin.readline().strip() != 'DONE':
            raise TimeoutError('device login not confirmed')

    def login(self):
        result = json.loads(self._worker('/opt/hermes/.venv/bin/python', '-I', '-B',
                                         '/opt/worker-preflight.py', timeout=35))
        if result != {'worker_owner_git': True, 'credential_helper_configured': True}:
            raise ValueError('worker owner/configuration preflight failed')
        self.pause(self.worker_id, min(600, self.deadline - time.monotonic()))

    def github_reads(self):
        result = json.loads(self._worker('/opt/hermes/.venv/bin/python', '-I', '-B',
                                         '/opt/worker-probe.py', timeout=45))
        if result != {'authenticated': True, 'task_open': True, 'git_read': True}:
            raise ValueError('worker authenticated read-only checks failed')

    def _stop_claim_runtime(self):
        """Terminate the exact container, not merely its Docker client.

        The claim/worktree/journals survive. Failure or uncertain inspect is
        never represented as a stopped runtime; no second dispatch is allowed.
        """
        ident = self.worker_id
        self._container(ident, 'inbox-worker')
        self._docker('stop', '--time', '5', ident, timeout=20)
        self._container(ident, 'inbox-worker', running=False)
        self.runtime_stopped = True

    def _inbox(self, action, *extra, timeout=30):
        try:
            result = self._worker('/opt/hermes/.venv/bin/python', '-I', '-B',
                '/workspace/runner/ops/github_inbox/inboxctl.py', action,
                '--enrollment', '/private/inbox/enrollment.json',
                '--state', '/state/github-inbox', *extra, timeout=timeout)
        except BaseException:
            if action == 'tick':
                try:
                    self._stop_claim_runtime()
                except BaseException:
                    self.runtime_stopped = False
            raise
        value = json.loads(result)
        if not isinstance(value, dict):
            raise ValueError('inbox result invalid')
        return value

    def enroll_disabled(self):
        from root_signer import load_scope
        scope = load_scope(self.plan.signer_policy)
        self._inbox('enroll', '--start', scope.start, timeout=60)
        state = self._inbox('doctor')
        if state.get('enabled') is not False or state.get('claim') is not None:
            raise ValueError('enrollment not disabled')
        if state.get('cursor') != scope.cursors:
            raise ValueError('fresh cursor differs from root-protected signer scope')
        path = self.plan.state / 'github-inbox'
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != self.plan.uid or info.st_mode & 0o077:
            raise PermissionError('enrollment identity unverified')
        self.enrollment_inode = str(info.st_ino)
        return (Owned('enrollment', self.enrollment_inode, self.plan.attempt),)

    def enable_inbox(self):
        result = self._inbox('enable')
        if result.get('enabled') is not True or result.get('claim') is not None:
            raise ValueError('inbox enable/readback mismatch')
        return ()  # In-process one-shot: no timer or second consumer installed.

    def one_bridge_claim(self):
        from root_signer import GitHub, load_scope, openssl_sign, openssl_verify, sign_scan
        scope = load_scope(self.plan.signer_policy)
        check_signer_binding(self.plan, scope)
        if str((self.plan.state / 'github-inbox').lstat().st_ino) != self.enrollment_inode:
            raise ValueError('enrollment root changed')
        client = self.signer or GitHub(self.plan.signer_token, deadline=self.deadline - CLEANUP_RESERVE)
        # A new manager instruction may arrive during this bounded operator entry.
        while time.monotonic() < self.deadline - CLEANUP_RESERVE - SCAN_RESERVE:
            scan_deadline = self.deadline - CLEANUP_RESERVE - SCAN_RESERVE
            grant = sign_scan(scope, self.plan.signer_state_root, client,
                lambda payload, *, deadline: openssl_sign(self.plan.signer_key, payload, deadline=deadline),
                verify=lambda payload, sig, *, deadline: openssl_verify(
                    self.plan.signer_public, payload, sig, deadline=deadline), deadline=scan_deadline)
            if grant is not None:
                available = self.deadline - time.monotonic() - CLEANUP_RESERVE
                if available <= 0:
                    return ()  # Signed grant exists, but no worker claim was invoked.
                result = self._inbox('tick', timeout=min(3600, available))
                self.claim_status = result
                if result.get('status') != 'review-ready':
                    raise ValueError('inbox/Bridge claim blocked or ambiguous')
                return ()
            time.sleep(min(60, max(0, self.deadline - time.monotonic() -
                                   CLEANUP_RESERVE - SCAN_RESERVE)))
        return ()  # No effect; the lifecycle may clean up exact known IDs.

    def reconcile(self):
        state = self._inbox('doctor')
        claim = state.get('claim')
        if claim is None and self.claim_status is None:
            return 'blocked'  # Empty feed; no worker claim was made.
        if not isinstance(claim, dict) or claim.get('publication_intent') is not None:
            return 'unknown'
        if claim.get('status') != 'review-ready' or not self.claim_status:
            return 'blocked'
        if (self.claim_status.get('status') != 'review-ready' or
                self.claim_status.get('claim', {}).get('grant_id') != claim.get('grant_id') or
                self.claim_status.get('claim', {}).get('queue_id') != claim.get('queue_id') or
                not isinstance(claim.get('queue_id'), str) or
                not re.fullmatch(r'[0-9a-f]{32}', claim['queue_id'])):
            return 'unknown'
        # Execute hash-checked root-only bytes, never a worker's code or JSON.
        # The root credential independently GETs every issue/PR/head/CI receipt.
        from root_signer import GitHub, load_scope
        scope = load_scope(self.plan.signer_policy)
        spec = importlib.util.spec_from_file_location(
            '_protected_bridge_readback', self.plan.bundle / 'bridge_readback.py')
        if spec is None or spec.loader is None:
            raise ValueError('protected verifier unavailable')
        verifier = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(verifier)
        client = self.github or GitHub(self.plan.signer_token, deadline=self.deadline)
        remote = verifier.verify(self.plan.state / 'queue', claim['queue_id'],
                                 scope.body_digest, scope.authority_identity, client.get)
        if not isinstance(remote, dict) or remote.get('verified') is not True:
            return 'blocked'
        if (not isinstance(remote.get('run_id'), str) or
                not re.fullmatch(r'[0-9a-f]{32}', remote['run_id']) or
                not isinstance(remote.get('head'), str) or
                not re.fullmatch(r'[0-9a-f]{40}', remote['head']) or
                remote.get('observed_ci') not in ('success', 'failure', 'pending', 'unknown') or
                not isinstance(remote.get('pr_url'), str) or
                not re.fullmatch(r'https://github\.com/aliercankonus/signal-desk-prediction/pull/[1-9][0-9]*', remote['pr_url'])):
            return 'unknown'
        self.remote_result = remote
        return 'review-ready'  # CI is observed for this exact head, not necessarily complete.

    def inspect_owned(self, resources):
        try:
            if not self.baseline or not resources:
                return False
            if any(not isinstance(x, Owned) or x.proof != self.plan.attempt for x in resources):
                return False
            observed = {(x.kind, x.ident) for x in resources}
            required = {('worker', self.worker_id), ('proxy', self.proxy_id),
                        ('firewall', 'SD_ONCE_IN'),
                        ('network', self.network_ids.get('worker_isolated')),
                        ('network', self.network_ids.get('proxy_uplink'))}
            if self.enrollment_inode is not None:
                required.add(('enrollment', self.enrollment_inode))
            if observed != required or len(observed) != len(resources):
                return False
            self._container(self.worker_id, 'inbox-worker')
            self._container(self.proxy_id, 'connect-proxy')
            if self._call(['bash', self.plan.bundle / 'worker_firewall.sh', 'status']).strip() != '':
                # The helper may print a bounded marker; exit status is the gate.
                pass
            if (self.enrollment_inode is not None and
                    (self.plan.state / 'github-inbox').lstat().st_ino != int(self.enrollment_inode)):
                return False
            return True
        except (ValueError, OSError, subprocess.SubprocessError, TimeoutError, KeyError):
            return False

    def cleanup(self, resources):
        if self.inspect_owned(resources) is not True:
            raise ValueError('owned resource changed before cleanup')
        # Keep queue, auth, context, inbox cursor, worktree, signer journal and
        # historical state. Disable intake first, then remove exact Docker IDs.
        if self.enrollment_inode is not None:
            state = self._inbox('disable')
            if state.get('enabled') is not False:
                raise ValueError('inbox disable not observed')
        for ident, service in ((self.worker_id, 'inbox-worker'), (self.proxy_id, 'connect-proxy')):
            self._container(ident, service)
            self._docker('stop', '--time', '5', ident, timeout=15)
            self._docker('rm', ident, timeout=15)
            if ident in self._docker('ps', '-aq', '--no-trunc', timeout=10).splitlines():
                raise ValueError('exact container still present')
            if service == 'inbox-worker':
                self._call(['bash', self.plan.bundle / 'worker_firewall.sh', 'status'])
                self._call(['bash', self.plan.bundle / 'worker_firewall.sh', 'rollback'],
                           timeout=30, env={'AUTODEV_FIREWALL_APPROVED': 'yes-for-reviewed-network'})
        for role in ('worker_isolated', 'proxy_uplink'):
            self._network(role)  # Existing helper requires empty exact labeled network.
            self._docker('network', 'rm', self.network_ids[role], timeout=20)
        return resources

    def cleanup_readback(self, resources):
        if self.baseline is None:
            return False
        if self.enrollment_inode is not None:
            state_file = self.plan.state / 'github-inbox' / 'state.json'
            observed = json.loads(worker_private_bytes(state_file, self.plan.uid, 8192))
            if ((self.plan.state / 'github-inbox').lstat().st_ino != int(self.enrollment_inode) or
                    observed['enabled'] is not False):
                return False
        if (self._docker('ps', '-aq', '--no-trunc') != self.baseline[0] or
                self._docker('network', 'ls', '-q', '--no-trunc') != self.baseline[1]):
            return False
        rules = self._call(['iptables', '-S'])
        return 'SD_ONCE_IN' not in rules and 'SD_ONCE_FWD' not in rules

    def report(self, sanitized):
        from root_signer import GitHub, canonical
        if sanitized.get('cleanup_verified') is not True:
            raise ValueError('cannot report before cleanup')
        client = self.github or GitHub(self.plan.signer_token, deadline=self.deadline)
        self.report_text = canonical({'operator_attempt': self.plan.attempt,
            'result': sanitized['result'], 'cleanup_verified': True,
            'failure': sanitized['failure'], 'task': 43,
            'remote_result': self.remote_result,
            'note': 'CI and manager approval require independent readback'}).decode('ascii')
        return str(client.publish(41, self.report_text))

    def report_readback(self, receipt, sanitized):
        from root_signer import GitHub
        client = self.github or GitHub(self.plan.signer_token, deadline=self.deadline)
        row = client.comment(41, int(receipt))
        return (row.get('id') == int(receipt) and row.get('issue_url') ==
                f'https://api.github.com/repos/{REPO}/issues/41' and
                row.get('body') == self.report_text)


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review', action='store_true')
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--plan', type=Path)
    args = parser.parse_args()
    if args.review and not args.execute:
        print('REVIEW ONLY: dormant root entry; no installation, credential or task action')
        return 0
    if not args.execute or args.plan is None or os.geteuid() != 0:
        parser.error('NO-GO: explicit separately approved root operation and private plan required')
    # A flag is not proof of App exclusivity, worker mount/credential isolation,
    # network acceptance, operator ownership or manager authorization.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    plan = load_plan(args.plan)
    deadline = time.monotonic() + plan.overall_seconds
    journal = Journal(plan.journal_parent / plan.attempt, plan.attempt)
    old_term = signal.getsignal(signal.SIGTERM)
    def interrupt(_signum, _frame):
        raise KeyboardInterrupt('operator interrupted')
    signal.signal(signal.SIGTERM, interrupt)
    try:
        outcome = run_once(journal, HostOperations(plan, runner=CommandRunner(deadline=deadline),
                                                    deadline=deadline), deadline=deadline)
    finally:
        signal.signal(signal.SIGTERM, old_term)
    print(json.dumps({k: outcome[k] for k in ('status', 'phase', 'unresolved_effect',
                                              'cleanup_verified', 'report_receipt')}, sort_keys=True))
    return 0 if outcome['status'] == 'review-ready' and outcome['cleanup_verified'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
