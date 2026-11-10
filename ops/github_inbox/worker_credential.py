"""Dedicated worker Git credential protocol; no network or credential mutation."""
import os
from pathlib import Path
import re
import stat
import sys

TOKEN = Path('/private/auth/github-token')
GITCONFIG = '''# Dedicated worker only; no credential value in this configuration.
[user]
    name = Signal Desk Worker
    email = 35579049+aliercankonus@users.noreply.github.com
[credential]
    helper =
[credential "https://github.com"]
    helper = !/opt/hermes/.venv/bin/python -I -B /opt/worker-credential.py
    useHttpPath = true
'''


def read_token():
    if os.geteuid() != 10000 or os.getegid() != 10000:
        raise PermissionError('worker identity')
    for p in (TOKEN.parent, *TOKEN.parent.parents):
        s = p.lstat()
        if not stat.S_ISDIR(s.st_mode) or s.st_uid not in (0, 10000) or s.st_mode & 0o022:
            raise PermissionError('token ancestry')
    before = TOKEN.lstat()
    if (not stat.S_ISREG(before.st_mode) or before.st_uid != 10000 or before.st_gid != 10000 or
            stat.S_IMODE(before.st_mode) != 0o400 or before.st_nlink != 1 or not 1 <= before.st_size <= 512):
        raise PermissionError('token metadata')
    fd = os.open(TOKEN, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    with os.fdopen(fd, 'rb') as f:
        opened = os.fstat(f.fileno()); data = f.read(513); after = os.fstat(f.fileno())
    named = TOKEN.lstat()
    identity = lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_mode,s.st_uid,s.st_gid,s.st_nlink)
    if not identity(before) == identity(opened) == identity(after) == identity(named) or len(data) != before.st_size:
        raise PermissionError('token changed')
    if not re.fullmatch(rb'github_pat_[A-Za-z0-9_]{32,500}', data):
        raise ValueError('token format')
    return data


def credential(operation, data, reader=read_token):
    # Git invokes store/erase after auth attempts; never mutate the root-installed
    # file or reveal a token for those operations, even if their input is secret.
    if operation in ('store', 'erase'): return b''
    if operation != 'get' or len(data) > 4096 or b'\0' in data: raise ValueError('credential request')
    values = {}
    for line in data.splitlines():
        if not line: break
        key, sep, value = line.partition(b'=')
        if not sep or any(c < 32 or c > 126 for c in line): raise ValueError('credential record')
        if key == b'wwwauth[]': continue  # Bounded challenge metadata, never executed.
        if key not in (b'protocol', b'host', b'path', b'username') or key in values:
            raise ValueError('credential fields')
        values[key] = value
    if (values.get(b'protocol') != b'https' or values.get(b'host') != b'github.com' or
            values.get(b'username', b'x-access-token') != b'x-access-token' or
            values.get(b'path', b'aliercankonus/signal-desk-prediction') not in
            (b'aliercankonus/signal-desk-prediction', b'aliercankonus/signal-desk-prediction.git')):
        raise ValueError('credential scope')
    # Host-only is needed by frozen Bridge GitHubREST's git credential fill.
    # The helper cannot infer a REST route here. Server-side repository-specific
    # grants and the unchanged REST allowlist remain required, never broadened.
    token = reader()
    if not isinstance(token, bytes) or not re.fullmatch(rb'github_pat_[A-Za-z0-9_]{32,500}', token):
        raise ValueError('credential format')
    return b'username=x-access-token\npassword='+token+b'\n\n'


def main():
    try:
        if len(sys.argv) != 2: raise ValueError('operation')
        data = sys.stdin.buffer.read(4097)
        output = credential(sys.argv[1], data)
        sys.stdout.buffer.write(output)
        return 0
    except Exception:
        # No exception text, request, file path or credential on either log stream.
        sys.stderr.write('worker credential unavailable\n')
        return 1


if __name__ == '__main__': raise SystemExit(main())
