#!/usr/bin/env python3
"""Future operator-only STAGING entry. No signer, login, enrollment or dispatch.

Install this file from its independently verified immutable merge, not a mutable
checkout. --stage consumes a private root-only spec; failures retain partial
fresh directories for manual review and never retry or overwrite an old run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import stat
import subprocess
import sys
import time

REPO = 'aliercankonus/signal-desk-prediction'
MERGE = 'eac843de7967d48cce56ee9a198750e98754a2de'
RUNNER_PIN = 'e84021a786004456a12de9e25eae50d191da6cf1'
TASK_DIGEST = 'c9e4e393ccc506954f0a18e6eaeea7c82ff598b0b41eac642d7f88da1fca73c6'
BRANCH = 'issue43-one-shot-review-note'
SIGNER_STATE = '/var/lib/signal-desk/issue41-signer-claims'
PATH = '/usr/sbin:/sbin:/usr/bin:/bin'
ARTIFACTS = frozenset(('ops/bridge_one_shot/bridge_readback.py',
    'ops/bridge_one_shot/compose.operator.yml', 'ops/bridge_one_shot/connect_proxy.py',
    'ops/bridge_one_shot/network_preflight.py', 'ops/bridge_one_shot/network_resources.py',
    'ops/bridge_one_shot/operator_artifacts.json', 'ops/bridge_one_shot/operator_host.py',
    'ops/bridge_one_shot/operator_lifecycle.py', 'ops/bridge_one_shot/worker_firewall.sh',
    'ops/github_inbox/root_signer.py', 'ops/github_inbox/worker_probe.py'))
PLAN_KEYS = ('attempt', 'bundle', 'source', 'merge', 'image', 'uid', 'gid',
    'runner', 'state', 'auth', 'context', 'home', 'venv', 'inbox', 'signer_token',
    'signer_key', 'signer_public', 'signer_policy', 'signer_state_root',
    'overall_seconds', 'journal_parent')
PATH_KEYS = frozenset(('source', 'bundle', 'runner', 'state', 'auth', 'context',
    'home', 'inbox', 'journal_parent', 'signer_state_root', 'signer_key',
    'signer_token', 'signer_public', 'signer_policy', 'plan', 'venv'))
DEST_KEYS = ('bundle', 'runner', 'state', 'auth', 'context', 'home', 'inbox',
             'journal_parent', 'signer_state_root', 'signer_policy', 'plan')
SPEC_KEYS = (set(PLAN_KEYS) | {'plan', 'task_body_sha256', 'requirements_sha256',
    'python_version', 'pytest_version', 'test_python', 'start', 'cursors',
    'git_name', 'git_email', 'excluded_roots'})
STAGING_DEADLINE = None
COMPOSE_ENV_KEYS = frozenset(('HERMES_IMAGE_REF','HERMES_UID','HERMES_GID',
    'SD_ATTEMPT_ID','BRIDGE_RUNNER_HOST','BRIDGE_STATE_PARENT_HOST','BRIDGE_AUTH_DIR_HOST',
    'BRIDGE_CONTEXT_DIR_HOST','BRIDGE_HOME_HOST','BRIDGE_VENV_HOST',
    'BRIDGE_INBOX_CONFIG_HOST','BRIDGE_REVIEW_HOST'))
# Matches the reviewed Hermes config-set output, but is staged only into a
# fresh dedicated worker home. Never import an operator/agent auth store.
PROVIDER_CONFIG = b'auth:\n  adopt_external_logins: false\n  codex_login_flow: device_code\n'


def command(argv, *, run=None, env=None):
    """Bounded, non-shell administrative command with no ambient auth/config."""
    compose = (isinstance(argv, list) and len(argv) == 11 and
        argv[:5] == ['docker','compose','--env-file','/dev/null','-f'] and
        isinstance(argv[5], str) and argv[5].endswith('/compose.operator.yml') and
        argv[6:] == ['--profile','execution','config','--format','json'])
    if (not isinstance(argv, list) or not argv or argv[0] not in ('git', 'docker') or
            any(not isinstance(a, str) or '\x00' in a for a in argv) or
            any(a in ('--execute', 'up', 'tick', 'run', 'sign', 'publish', 'push') for a in argv) or
            '-c' in argv or
            (argv[0] == 'git' and len(argv) > 1 and argv[1] not in
             ('clone', '-C', 'cat-file', 'merge-base') and not argv[1].startswith('--git-dir=')) or
            (argv[0] == 'docker' and (len(argv) < 2 or argv[1] not in
             ('ps', 'inspect', 'image', 'network') and not compose)) or
            (compose and (set(env or {}) != COMPOSE_ENV_KEYS or
             any(not isinstance(value, str) or '\n' in value or '\x00' in value
                 for value in (env or {}).values())))):
        raise ValueError('command outside staging scope')
    if compose:
        _path(argv[5])
    if env and any(not k.isupper() or any(word in k for word in
        ('TOKEN','KEY','SECRET','PASSWORD')) for k in env):
        raise ValueError('secret or invalid command environment')
    if run is not None:
        return run(argv, timeout=15)
    remaining = 15 if STAGING_DEADLINE is None else min(15, STAGING_DEADLINE - time.monotonic())
    if remaining <= 0:
        raise TimeoutError('staging wall budget exhausted')
    clean = {'PATH': PATH, 'HOME': '/nonexistent', 'LC_ALL': 'C',
             'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null',
             'GIT_TERMINAL_PROMPT': '0', 'GCM_INTERACTIVE': 'never'}
    if env:
        clean.update(env)
    return _bounded_run(argv, env=clean, timeout=remaining)


def _bounded_run(argv, *, timeout, env=None):
    child = subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             start_new_session=True)
    output = {child.stdout: bytearray(), child.stderr: bytearray()}
    deadline = time.monotonic() + timeout
    selector = selectors.DefaultSelector()
    try:
        for stream in output:
            selector.register(stream, selectors.EVENT_READ)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('staging command deadline')
            for key, _ in selector.select(timeout=min(.1, remaining)):
                chunk = os.read(key.fd, min(8192, 65537 - len(output[key.fileobj])))
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                output[key.fileobj].extend(chunk)
                if len(output[key.fileobj]) > 65536:
                    raise ValueError('staging command output bound')
        if child.wait(timeout=max(.001, deadline - time.monotonic())) != 0:
            raise RuntimeError('staging command failed (output withheld)')
        return bytes(output[child.stdout])
    finally:
        selector.close()
        if child.poll() is None:
            try: os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            child.wait(timeout=2)
        child.stdout.close()
        child.stderr.close()


def verify_compose(rendered, cfg):
    """Exact proposed bind allowlist; a static config is not host isolation proof."""
    expected = {
      'inbox-worker': [('runner','/workspace/runner',False),('state','/state',False),
        ('auth','/private/auth',True),('context','/private/context',True),
        ('home','/worker-home',False),
        ('venv','/opt/data/signal-desk-tooling/venvs/issue26-recovery-python314-20261030',True),
        ('inbox','/private/inbox',True),('bundle/worker_probe.py','/opt/worker-probe.py',True)],
      'connect-proxy': [('bundle/connect_proxy.py','/opt/connect-proxy.py',True)]}
    if not isinstance(rendered, dict) or set(rendered.get('services', {})) != set(expected):
        raise PermissionError('unexpected Compose service')
    for name, mounts in expected.items():
        service = rendered['services'][name]
        if service.get('restart') != 'no':
            raise PermissionError('Compose restart must be disabled')
        actual = service.get('volumes')
        if not isinstance(actual, list) or len(actual) != len(mounts):
            raise PermissionError('unexpected Compose bind count')
        for (key, target, readonly), item in zip(mounts, actual):
            source = cfg['bundle'] + '/' + key.split('/',1)[1] if key.startswith('bundle/') else cfg[key]
            if (item.get('type') != 'bind' or item.get('source') != source or
                    item.get('target') != target or item.get('read_only', False) is not readonly or
                    item.get('bind', {}).get('create_host_path', False) is not False):
                raise PermissionError('unexpected Compose bind or secret exposure')


def _path(value):
    if (not isinstance(value, str) or not value.startswith('/') or '\x00' in value or
            '..' in Path(value).parts or len(value) > 512):
        raise ValueError('absolute canonical operator path required')
    path = Path(value)
    if str(path) != value or path == Path('/'):
        raise ValueError('operator path not canonical')
    return path


def _overlap(a, b):
    return a == b or a in b.parents or b in a.parents


def validate_spec(cfg):
    """Pure validation and existing-destination refusal before any command/write."""
    if not isinstance(cfg, dict) or set(cfg) != SPEC_KEYS:
        raise ValueError('operator spec fields mismatch')
    paths = {key: _path(cfg[key]) for key in PATH_KEYS}
    if (cfg['merge'] != MERGE or cfg['task_body_sha256'] != TASK_DIGEST or
            cfg['signer_state_root'] != SIGNER_STATE or
            not re.fullmatch(r'sha256:[0-9a-f]{64}', cfg['image']) or
            type(cfg['uid']) is not int or cfg['uid'] < 1 or
            type(cfg['gid']) is not int or cfg['gid'] < 1 or
            not re.fullmatch(r'[a-z][a-z0-9-]{5,63}', cfg['attempt']) or
            type(cfg['overall_seconds']) is not int or not 600 <= cfg['overall_seconds'] <= 7200 or
            not re.fullmatch(r'[0-9a-f]{64}', cfg['requirements_sha256']) or
            not all(isinstance(cfg[k], str) and re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', cfg[k])
                    for k in ('python_version', 'pytest_version')) or
            not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ', cfg['start']) or
            not isinstance(cfg['cursors'], dict) or set(cfg['cursors']) != {'41', '45'} or
            any(type(x) is not int or x < 0 for x in cfg['cursors'].values()) or
            not all(isinstance(cfg[k], str) and 1 <= len(cfg[k]) <= 128 and
                    not any(ord(ch) < 32 for ch in cfg[k]) for k in ('git_name', 'git_email')) or
            not isinstance(cfg['excluded_roots'], list) or not cfg['excluded_roots']):
        raise ValueError('operator spec pin/identity invalid')
    _path(cfg['test_python'])
    excluded = [_path(p) for p in cfg['excluded_roots']]
    destinations = [paths[k] for k in DEST_KEYS]
    if len(set(destinations)) != len(destinations):
        raise ValueError('duplicate destination')
    for key in DEST_KEYS:
        p = paths[key]
        if p.exists() or p.is_symlink():
            raise FileExistsError('operator destination already exists: ' + key)
        for other in excluded + [paths[x] for x in ('source', 'venv', 'signer_key',
                'signer_public', 'signer_token')] + [paths[x] for x in DEST_KEYS if x != key]:
            # The fixed state/queue and future child layout are created separately;
            # other fresh roots must not contain one another.
            if _overlap(p, other):
                raise ValueError('operator destination overlap: ' + key)
    for p in excluded:
        if not p.is_dir() or p.is_symlink():
            raise ValueError('excluded root absent or symlinked')
    if any(_overlap(paths[x], paths[y]) for x in ('source','venv','signer_key','signer_public','signer_token')
           for y in ('source','venv','signer_key','signer_public','signer_token') if x < y):
        raise ValueError('protected input overlap')
    if paths['signer_policy'].parent != paths['plan'].parent:
        raise ValueError('root metadata must share private parent')
    handoff = paths['plan'].parent / (paths['plan'].stem + '-handoff.json')
    if handoff.exists() or handoff.is_symlink():
        raise FileExistsError('root handoff record exists')
    return paths


def build_records(cfg, public):
    policy = {'repo': REPO, 'issue': 43, 'body_digest': TASK_DIGEST,
              'base': RUNNER_PIN, 'branch': BRANCH}
    identity = hashlib.sha256(json.dumps(policy, sort_keys=True,
                                separators=(',', ':')).encode()).hexdigest()
    scope = {'repo': REPO, 'task_issue': 43, 'body_digest': TASK_DIGEST,
             'authority_identity': identity, 'runner_commit': RUNNER_PIN,
             'start': cfg['start'], 'cursors': cfg['cursors'], 'app_id': 1144995}
    context = {'test_python': cfg['test_python'],
               'requirements_sha256': cfg['requirements_sha256'],
               'runner_commit': RUNNER_PIN, 'python_version': cfg['python_version'],
               'pytest_version': cfg['pytest_version']}
    enrollment = {'repo': REPO, 'issues': [41, 45], 'task_issue': 43,
                  'runner': '/workspace/runner', 'runner_commit': RUNNER_PIN,
                  'queue': '/state/queue', 'authorization': '/private/auth/authorization.json',
                  'context': '/private/context/context.json',
                  'public_key': '/private/inbox/manager-public.pem',
                  'public_key_sha256': hashlib.sha256(public).hexdigest(),
                  'interval_seconds': 300}
    plan = {k: cfg[k] for k in PLAN_KEYS}
    handoff = {'schema': 1, 'merge': MERGE, 'runner_commit': RUNNER_PIN,
               'manager_exclusive_invocation': 'UNPROVEN', 'activation': 'NO-GO',
               'timer': 'DISABLED', 'scope': 'one bounded in-process attempt only'}
    return {'authorization.json': policy, 'context.json': context,
            'enrollment.json': enrollment, 'signer-policy.json': scope,
            'operator-plan.json': plan, 'handoff.json': handoff,
            'provider-config.yaml': PROVIDER_CONFIG}


def _trusted(path, *, owner, private=False):
    for item in (path, *path.parents):
        info = item.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, owner) or
                info.st_mode & 0o022 or (private and item == path and info.st_mode & 0o077)):
            raise PermissionError('untrusted operator ancestor')


def _nearest(path, owner):
    p = path
    while not p.exists() and not p.is_symlink():
        p = p.parent
    _trusted(p, owner=owner)


def _regular(path, owner, *, limit=8192):
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != owner or
            info.st_mode & 0o077 or not 0 < info.st_size <= limit):
        raise PermissionError('private input metadata invalid')


def _time_gate():
    if STAGING_DEADLINE is not None and time.monotonic() >= STAGING_DEADLINE:
        raise TimeoutError('staging wall budget exhausted')


def _write(path, data, owner, group):
    _time_gate()
    encoded = json.dumps(data, sort_keys=True, separators=(',', ':')).encode() + b'\n' if isinstance(data, dict) else data
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as output:
        output.write(encoded)
        os.fchown(output.fileno(), owner, group)
        os.fsync(output.fileno())


def _mkdir(path, owner, group):
    _time_gate()
    path.mkdir(mode=0o700)  # No parents=True; existing ancestor must be trusted.
    os.chown(path, owner, group)
    parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try: os.fsync(parent)
    finally: os.close(parent)


def _contained_mounts(destinations):
    """Inspect actual existing Docker mounts without environment/secret values."""
    ids = command(['docker', 'ps', '-aq', '--no-trunc']).decode().splitlines()
    if len(ids) > 32 or any(not re.fullmatch('[0-9a-f]{64}', i) for i in ids):
        raise ValueError('Docker inventory incomplete')
    for ident in ids:
        raw = command(['docker', 'inspect', '--type', 'container', '--format', '{{json .Mounts}}', ident])
        mounts = json.loads(raw)
        if not isinstance(mounts, list):
            raise ValueError('Docker mounts invalid')
        for mount in mounts:
            if mount.get('Type') == 'bind':
                source = _path(mount.get('Source'))
                if any(_overlap(source, dest) for dest in destinations):
                    raise PermissionError('new stage overlaps existing container bind')


def _chown_fresh_tree(root, uid, gid):
    """Never follow symlinks; only the fresh, exact checkout is eligible."""
    for parent, dirs, files in os.walk(root, followlinks=False):
        _time_gate()
        for name in dirs + files:
            item = Path(parent) / name
            if item.is_symlink():
                raise ValueError('runner symlink requires separate review')
            os.chown(item, uid, gid, follow_symlinks=False)
    os.chown(root, uid, gid)


def stage(cfg):
    global STAGING_DEADLINE
    if STAGING_DEADLINE is not None:
        raise RuntimeError('staging already in progress')
    STAGING_DEADLINE = time.monotonic() + 600
    try:
        return _stage_once(cfg)
    finally:
        STAGING_DEADLINE = None


def _stage_once(cfg):
    if os.geteuid() != 0:
        raise PermissionError('root-only future staging')
    paths = validate_spec(cfg)
    for key, p in paths.items():
        _nearest(p if key in ('source', 'venv') else p.parent,
                 cfg['uid'] if key == 'venv' else 0)
    for p in (paths['source'], paths['signer_token'].parent,
              paths['signer_key'].parent, paths['signer_public'].parent,
              paths['plan'].parent):
        _trusted(p, owner=0, private=True)
    for k in ('signer_token', 'signer_key', 'signer_public'):
        _regular(paths[k], 0)
    _trusted(paths['venv'], owner=cfg['uid'], private=True)
    venv_config = (paths['venv'] / 'pyvenv.cfg').lstat()
    if not stat.S_ISREG(venv_config.st_mode) or venv_config.st_uid != cfg['uid'] or venv_config.st_size > 8192:
        raise PermissionError('reviewed venv metadata invalid')
    # Public bytes only. Private key/token values are never opened or logged.
    public = paths['signer_public'].read_bytes()
    if not public.startswith(b'-----BEGIN PUBLIC KEY-----\n'):
        raise ValueError('public verifier format invalid')
    if command(['git', '--git-dir=' + str(paths['source']), 'cat-file', '-t', MERGE]) != b'commit\n':
        raise ValueError('merged object absent')
    if command(['git', '--git-dir=' + str(paths['source']), 'cat-file', '-t', RUNNER_PIN]) != b'commit\n':
        raise ValueError('runner object absent')
    if command(['git', '--git-dir=' + str(paths['source']), 'merge-base', MERGE, RUNNER_PIN]).strip() != RUNNER_PIN.encode():
        raise ValueError('reviewed runner not in merge ancestry')
    raw = command(['git', '--git-dir=' + str(paths['source']), 'show',
                   MERGE + ':ops/bridge_one_shot/operator_artifacts.json'])
    index = json.loads(raw)
    if index != {'schema': 1, 'runner_commit': RUNNER_PIN, 'files': sorted(ARTIFACTS)}:
        raise ValueError('merged artifact inventory changed')
    blobs = {}
    for name in ARTIFACTS:
        _time_gate()
        spec = MERGE + ':' + name
        size = int(command(['git', '--git-dir=' + str(paths['source']), 'cat-file', '-s', spec]))
        if not 0 < size <= 65536:
            raise ValueError('merged blob size invalid')
        blob = command(['git', '--git-dir=' + str(paths['source']), 'show', spec])
        if len(blob) != size:
            raise ValueError('merged blob changed')
        blobs[name] = blob
    req = command(['git', '--git-dir=' + str(paths['source']), 'show', RUNNER_PIN + ':requirements.txt'])
    if hashlib.sha256(req).hexdigest() != cfg['requirements_sha256']:
        raise ValueError('runner requirements digest mismatch')
    if command(['docker', 'image', 'inspect', '--format', '{{.Id}}', cfg['image']]).strip() != cfg['image'].encode():
        raise ValueError('image identity mismatch')
    # Version 2: obtain only variable names at the Docker formatting boundary.
    raw_names = command(['docker', 'image', 'inspect', '--format',
        '{{range .Config.Env}}{{println (index (split . "=") 0)}}{{end}}', cfg['image']])
    names = raw_names.decode('ascii').splitlines()
    if names and names[-1] == '':
        names.pop()  # Docker's extra terminal LF, not an environment entry.
    if len(names) > 256 or any(not re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,127}', x) or
        re.search(r'(TOKEN|SECRET|KEY|PASSWORD|CREDENTIAL|AUTH)', x, re.I) for x in names):
        raise PermissionError('image credential environment cannot be excluded')
    _contained_mounts([paths[k] for k in DEST_KEYS] +
                      [paths[k] for k in ('source','signer_key','signer_token','signer_public')])
    existing = command(['docker', 'ps', '-aq', '--no-trunc', '--filter',
                        'label=com.docker.compose.project=signal-desk-bridge-once']).strip()
    nets = command(['docker', 'network', 'ls', '-q', '--no-trunc', '--filter',
                    'label=com.docker.compose.project=signal-desk-bridge-once']).strip()
    if existing or nets:
        raise FileExistsError('operator Compose resource exists')
    records = build_records(cfg, public)
    # No writes above this point. From here every created name is exclusive;
    # a failure preserves partial fresh state without rollback/retry.
    # Root runs clone/checkout/config/status below. Keep runner root-owned until
    # its last root Git command; Git's dubious-ownership guard stays enabled.
    for key in ('bundle','runner','state','auth','context','home','inbox','journal_parent','signer_state_root'):
        _mkdir(paths[key], 0 if key in ('bundle','runner','journal_parent','signer_state_root') else cfg['uid'],
               0 if key in ('bundle','runner','journal_parent','signer_state_root') else cfg['gid'])
    _mkdir(paths['state'] / 'queue', cfg['uid'], cfg['gid'])
    for name, blob in blobs.items():
        basename = Path(name).name
        target = paths['bundle'] / basename
        _write(target, blob, 0, 0)
        if basename in ('worker_probe.py', 'connect_proxy.py'):
            target.chmod(0o444)
    checks = {name: hashlib.sha256(blob).hexdigest() for name, blob in blobs.items()}
    _write(paths['bundle'] / 'merged-byte-manifest.json', {'schema': 1, 'merge': MERGE,
                                                           'sha256': checks}, 0, 0)
    if {x.name for x in paths['bundle'].iterdir()} != {Path(x).name for x in ARTIFACTS} | {'merged-byte-manifest.json'}:
        raise ValueError('staged bundle file set changed')
    for name, digest in checks.items():
        if hashlib.sha256((paths['bundle'] / Path(name).name).read_bytes()).hexdigest() != digest:
            raise ValueError('staged bundle bytes changed')
    compose_env = {'HERMES_IMAGE_REF':cfg['image'], 'HERMES_UID':str(cfg['uid']),
                   'HERMES_GID':str(cfg['gid']), 'SD_ATTEMPT_ID':cfg['attempt'],
                   'BRIDGE_RUNNER_HOST':cfg['runner'], 'BRIDGE_STATE_PARENT_HOST':cfg['state'],
                   'BRIDGE_AUTH_DIR_HOST':cfg['auth'], 'BRIDGE_CONTEXT_DIR_HOST':cfg['context'],
                   'BRIDGE_HOME_HOST':cfg['home'], 'BRIDGE_VENV_HOST':cfg['venv'],
                   'BRIDGE_INBOX_CONFIG_HOST':cfg['inbox'], 'BRIDGE_REVIEW_HOST':cfg['bundle']}
    rendered = json.loads(command(['docker','compose','--env-file','/dev/null','-f',
        str(paths['bundle'] / 'compose.operator.yml'),'--profile','execution','config','--format','json'],
        env=compose_env))
    verify_compose(rendered, cfg)
    # Fresh clone only. Never modify the old host runner or any old worktree.
    command(['git', 'clone', '--no-local', '--no-checkout', str(paths['source']), str(paths['runner'])])
    command(['git', '-C', str(paths['runner']), 'checkout', '--detach', RUNNER_PIN])
    command(['git', '-C', str(paths['runner']), 'remote', 'set-url', 'origin',
             'https://github.com/' + REPO + '.git'])
    command(['git', '-C', str(paths['runner']), 'config', '--local', 'user.name', cfg['git_name']])
    command(['git', '-C', str(paths['runner']), 'config', '--local', 'user.email', cfg['git_email']])
    if (command(['git', '-C', str(paths['runner']), 'rev-parse', 'HEAD']).strip() != RUNNER_PIN.encode() or
            command(['git', '-C', str(paths['runner']), 'status', '--porcelain=v1',
                     '--untracked-files=all']).strip()):
        raise ValueError('runner identity/cleanliness changed')
    # No root Git operation may follow this worker-ownership transition.
    _chown_fresh_tree(paths['runner'], cfg['uid'], cfg['gid'])
    for target, name, owner, group in ((paths['auth'] / 'authorization.json','authorization.json', cfg['uid'], cfg['gid']),
            (paths['context'] / 'context.json','context.json', cfg['uid'], cfg['gid']),
            (paths['inbox'] / 'enrollment.json','enrollment.json', cfg['uid'], cfg['gid']),
            (paths['signer_policy'],'signer-policy.json',0,0),
            (paths['plan'],'operator-plan.json',0,0),
            (paths['plan'].parent / (paths['plan'].stem + '-handoff.json'),'handoff.json',0,0)):
        _write(target, records[name], owner, group)
    _write(paths['home'] / 'config.yaml', records['provider-config.yaml'], cfg['uid'], cfg['gid'])
    _write(paths['inbox'] / 'manager-public.pem', public, cfg['uid'], cfg['gid'])
    # No network, signer, device login, enrollment, timer or task dispatch.
    return 'STAGED ONLY — activation NO-GO; manager-exclusive invocation UNPROVEN; --execute not called'


def _private_spec(path):
    if os.geteuid() != 0:
        raise PermissionError('root-only operator spec')
    p = _path(str(path))
    _trusted(p.parent, owner=0, private=True)
    _regular(p, 0, limit=16384)
    fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        raw = os.read(fd, 16385)
        if len(raw) != p.stat().st_size or len(raw) > 16384:
            raise ValueError('operator spec changed')
    finally:
        os.close(fd)
    return json.loads(raw)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Future root-only staging, never runtime execution')
    parser.add_argument('--stage', action='store_true', required=True)
    parser.add_argument('--spec', required=True, type=Path)
    args = parser.parse_args(argv)
    print(stage(_private_spec(args.spec)))


if __name__ == '__main__':
    main()
