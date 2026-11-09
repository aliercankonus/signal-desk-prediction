#!/usr/bin/env python3
"""Dormant root-terminal guide to a complete, exclusive bootstrap spec.

Preview is the default. No key/token contents, staging or runtime entry is read.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import select
import selectors
import signal
import stat
import subprocess
import sys
import time
import types

# The existing consumer is loaded in memory from its SHA-pinned Git blob;
# the reviewed installer has not yet installed a private source file.
BOOTSTRAP_SHA = 'e79f337fcbefc4f21f4d6d4abd2e30078227cb0913f242b552630fd110c1dd0d'
BOOTSTRAP_PIN = '665698113fcd7d8f7d10a75ee42f67d8a2131166'
TEST_PYTHON = '/opt/data/signal-desk-tooling/venvs/issue26-recovery-python314-20261030/bin/python'
INPUTS = (
    ('attempt', 'Fresh attempt ID (lowercase, e.g. attempt-issue41-2)'),
    ('source', 'Existing root-private bare Git object store'),
    ('fresh_parent', 'Existing root-private parent for fresh staging directories'),
    ('private_parent', 'Existing root-private parent for policy, plan and spec'),
    ('venv', 'Existing inspected worker-owned host venv'),
    ('image', 'Reviewed immutable Docker image ID (sha256:...)'),
    ('uid', 'Reviewed non-root worker UID'), ('gid', 'Reviewed non-root worker GID'),
    ('signer_key', 'Existing root-private key file path (metadata only)'),
    ('signer_public', 'Existing root-private public verifier path (metadata only)'),
    ('signer_token', 'Existing distinct root-private readback file path (metadata only)'),
    ('excluded_roots', 'Existing protected roots, comma separated (agent/application/data/release)'),
    ('requirements_sha256', 'Reviewed runner requirements SHA-256'),
    ('python_version', 'Reviewed venv Python version'),
    ('pytest_version', 'Reviewed venv pytest version'),
    ('git_name', 'Reviewed nonsecret worker Git author name'),
    ('git_email', 'Reviewed nonsecret worker Git author email'),
    ('cursor41', 'Exact latest #41 comment numeric ID'),
    ('cursor45', 'Exact latest #45 comment numeric ID'),
)


def _canonical(value):
    if not isinstance(value, str) or not value.startswith('/') or '<' in value or '>' in value or '\x00' in value or '..' in Path(value).parts or len(value) > 512 or str(Path(value)) != value or value == '/':
        raise ValueError('canonical absolute source required')
    return Path(value)


def _trusted_source(path, owner):
    for part in (path, *path.parents):
        info = part.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, owner) or info.st_mode & 0o022 or (part == path and info.st_mode & 0o077):
            raise PermissionError('untrusted source prerequisite')


def _bounded_command(argv):
    """Only one pinned Git read before loading the reviewed consumer."""
    if (len(argv) != 4 or argv[0] != 'git' or not argv[1].startswith('--git-dir=/') or
        argv[2:] != ['show', BOOTSTRAP_PIN + ':ops/bridge_one_shot/operator_bootstrap.py']):
        raise ValueError('bootstrap read outside scope')
    env = {'PATH': '/usr/sbin:/sbin:/usr/bin:/bin', 'HOME': '/nonexistent', 'LC_ALL': 'C',
           'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null',
           'GIT_TERMINAL_PROMPT': '0', 'GCM_INTERACTIVE': 'never'}
    child = subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, start_new_session=True)
    assert child.stdout is not None
    output = bytearray()
    deadline = time.monotonic() + 15
    selector = selectors.DefaultSelector()
    try:
        selector.register(child.stdout, selectors.EVENT_READ)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('bootstrap read deadline')
            for key, _ in selector.select(min(.1, remaining)):
                chunk = os.read(key.fd, min(8192, 65537 - len(output)))
                if not chunk:
                    selector.unregister(key.fileobj)
                else:
                    output.extend(chunk)
                    if len(output) > 65536:
                        raise ValueError('bootstrap source exceeds bound')
        if child.wait(timeout=max(.001, deadline - time.monotonic())):
            raise ValueError('bootstrap source prerequisite absent')
        return bytes(output)
    finally:
        selector.close()
        if child.poll() is None:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait(timeout=2)
        child.stdout.close()


def load_consumer(source, *, command=None, owner=None):
    path = _canonical(source)
    _trusted_source(path, os.geteuid() if owner is None else owner)
    getter = command or _bounded_command
    blob = getter(['git', '--git-dir=' + str(path), 'show',
                   BOOTSTRAP_PIN + ':ops/bridge_one_shot/operator_bootstrap.py'])
    if len(blob) != 26012 or hashlib.sha256(blob).hexdigest() != BOOTSTRAP_SHA:
        raise ValueError('bootstrap source prerequisite mismatch')
    module = types.ModuleType('reviewed_operator_bootstrap')
    exec(compile(blob, 'pinned-operator-bootstrap.py', 'exec'), module.__dict__)
    return module


def _reject_placeholders(value):
    if isinstance(value, dict):
        for member in value.values():
            _reject_placeholders(member)
    elif isinstance(value, list):
        for member in value:
            _reject_placeholders(member)
    elif isinstance(value, str) and (not value.strip() or '<' in value or '>' in value or
                                      any(ord(c) < 32 for c in value)):
        raise ValueError('placeholder or control character in input')


def prepare_spec(values, *, command=None, owner=0, now=None):
    """Read-only preflight against the exact bootstrap consumer; no output file."""
    if set(values) != {k for k, _ in INPUTS} - {'cursor41', 'cursor45'} | {'cursors'}:
        raise ValueError('operator input fields mismatch')
    _reject_placeholders(values)
    source = _canonical(values['source'])
    _trusted_source(source, owner)
    bootstrap = load_consumer(str(source), command=command)
    command = command or bootstrap.command
    source = bootstrap._path(values['source'])
    fresh = bootstrap._path(values['fresh_parent'])
    private = bootstrap._path(values['private_parent'])
    venv = bootstrap._path(values['venv'])
    for parent in (source, fresh, private):
        bootstrap._trusted(parent, owner=owner, private=True)
    bootstrap._trusted(venv, owner=values['uid'], private=True)
    info = (venv / 'pyvenv.cfg').lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != values['uid'] or not 0 < info.st_size <= 8192:
        raise PermissionError('reviewed venv prerequisite absent')
    for key in ('signer_key', 'signer_public', 'signer_token'):
        path = bootstrap._path(values[key])
        bootstrap._trusted(path.parent, owner=owner, private=True)
        try:
            bootstrap._regular(path, owner)
        except FileNotFoundError:
            raise PermissionError('private input prerequisite absent') from None
    if len({values[k] for k in ('signer_key', 'signer_public', 'signer_token')}) != 3:
        raise ValueError('private input paths overlap')
    attempt = values['attempt']
    if not isinstance(attempt, str) or not re.fullmatch(r'[a-z][a-z0-9-]{5,63}', attempt):
        raise ValueError('invalid attempt ID')
    cfg = {key: str(fresh / (attempt + '-' + key)) for key in
           ('bundle', 'runner', 'state', 'auth', 'context', 'home', 'inbox', 'journal_parent')}
    cfg.update({key: values[key] for key in ('attempt', 'source', 'venv', 'image', 'uid', 'gid',
        'signer_key', 'signer_public', 'signer_token', 'excluded_roots', 'requirements_sha256',
        'python_version', 'pytest_version', 'git_name', 'git_email', 'cursors')})
    cfg.update(merge=bootstrap.MERGE, task_body_sha256=bootstrap.TASK_DIGEST,
        signer_state_root=bootstrap.SIGNER_STATE, overall_seconds=1800,
        test_python=TEST_PYTHON, signer_policy=str(private / (attempt + '-signer-policy.json')),
        plan=str(private / (attempt + '-operator-plan.json')),
        start=now or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))
    bootstrap.validate_spec(cfg)  # includes existing destinations and excluded-root overlaps
    if command(['git', '--git-dir=' + str(source), 'rev-parse', '--is-bare-repository']) != b'true\n':
        raise ValueError('source object store prerequisite absent')
    for pin in (BOOTSTRAP_PIN, bootstrap.MERGE, bootstrap.RUNNER_PIN):
        if command(['git', '--git-dir=' + str(source), 'cat-file', '-t', pin]) != b'commit\n':
            raise ValueError('source object prerequisite absent')
    requirements = command(['git', '--git-dir=' + str(source), 'show',
                            bootstrap.RUNNER_PIN + ':requirements.txt'])
    if hashlib.sha256(requirements).hexdigest() != cfg['requirements_sha256']:
        raise ValueError('reviewed requirements prerequisite mismatch')
    if command(['docker', 'image', 'inspect', '--format', '{{.Id}}', cfg['image']]).strip() != cfg['image'].encode():
        raise ValueError('reviewed image prerequisite absent')
    return cfg


def write_spec(path, cfg, *, owner=0, command=None):
    """Exclusive 0600 publication; an existing or symlinked name is never replaced."""
    if os.geteuid() != owner:
        raise PermissionError('root operator identity required')
    bootstrap = load_consumer(cfg['source'], command=command)
    target = bootstrap._path(str(path))
    bootstrap._trusted(target.parent, owner=owner, private=True)
    if target != Path(cfg['plan']).parent / (cfg['attempt'] + '-bootstrap-spec.json'):
        raise ValueError('spec destination mismatch')
    bootstrap.validate_spec(cfg)
    data = json.dumps(cfg, sort_keys=True, separators=(',', ':')).encode() + b'\n'
    if len(data) > 16384:
        raise ValueError('spec exceeds consumer limit')
    parent = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(target.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600, dir_fd=parent)
        with os.fdopen(fd, 'wb') as output:
            output.write(data)
            os.fsync(output.fileno())
        os.fsync(parent)
    finally:
        os.close(parent)


def _prompt_values():
    result = {}
    with open('/dev/tty', 'r+') as tty:
        for key, label in INPUTS:
            tty.write(label + ': ')
            tty.flush()
            if not select.select([tty], [], [], 120)[0]:
                raise TimeoutError('operator input deadline')
            text = tty.readline(1025).rstrip('\n')
            if not text or len(text) > 1024:
                raise ValueError('missing or excessive operator input')
            if key in ('uid', 'gid', 'cursor41', 'cursor45'):
                if not text.isdecimal():
                    raise ValueError('numeric operator input required')
                result[key] = int(text)
            elif key == 'excluded_roots':
                result[key] = [s.strip() for s in text.split(',')]
            else:
                result[key] = text
    result['cursors'] = {'41': result.pop('cursor41'), '45': result.pop('cursor45')}
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description='Dormant root-only bootstrap spec guide (preview by default)')
    parser.add_argument('--write', action='store_true', help='explicitly publish a fresh 0600 spec')
    args = parser.parse_args(argv)
    if os.geteuid() != 0:
        raise SystemExit('STOP: root terminal required')
    try:
        cfg = prepare_spec(_prompt_values())
        if args.write:
            write_spec(Path(cfg['plan']).parent / (cfg['attempt'] + '-bootstrap-spec.json'), cfg)
            print('SPEC WRITTEN ONLY; source installation and staging NOT RUN. STOP for review.')
        else:
            print('PREVIEW READY; no spec written, no source installation or staging. STOP for review.')
    except (ValueError, PermissionError, FileNotFoundError, TimeoutError, OSError, RuntimeError, KeyError, TypeError) as exc:
        # Never echo private path values or command output on failure.
        print('STOP: prerequisites/inputs invalid (' + type(exc).__name__ + '); no retry over partial state', file=sys.stderr)
        raise SystemExit(2) from None


if __name__ == '__main__':
    main()
