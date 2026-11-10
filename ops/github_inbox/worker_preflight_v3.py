"""Actual worker owner/config check before provider handoff; no credential GET."""
import json
import os
from pathlib import Path
import subprocess
import stat
import resource
import tempfile
import re

class PreflightBlocked(Exception): pass


def tracking_keys(keys, call):
    allowed = {'core.repositoryformatversion','core.filemode','core.bare','core.logallrefupdates',
               'remote.origin.url','remote.origin.fetch','user.name','user.email'}
    pairs = {}
    for key in keys:
        if key in allowed: continue
        match = re.fullmatch(r'branch\.([A-Za-z0-9][A-Za-z0-9._/-]{0,127})\.(remote|merge)', key)
        if not match: raise PreflightBlocked('LOCAL_CONFIG_KEY')
        branch, field = match.groups()
        if key in pairs: raise PreflightBlocked('DUPLICATE_TRACKING_KEY')
        pairs[key] = (branch, field)
    for key,(branch,field) in pairs.items():
        if not all('branch.'+branch+'.'+suffix in pairs for suffix in ('remote','merge')):
            raise PreflightBlocked('INCOMPLETE_TRACKING_PAIR')
        expected = b'origin\n' if field=='remote' else ('refs/heads/'+branch+'\n').encode('ascii')
        if call(['config','--local','--no-includes','--get-all',key]) != expected:
            raise PreflightBlocked('TRACKING_VALUE')

PIN = 'e84021a786004456a12de9e25eae50d191da6cf1'
HELPER = '!/opt/hermes/.venv/bin/python -I -B /opt/worker-credential.py'
HELPER_MODULE = '/opt/worker-credential.py'


def check(runner=Path('/workspace/runner'), config=Path('/worker-home/gitconfig'), call=None):
    if os.getuid() != 10000 or os.getgid() != 10000: raise PermissionError('worker owner')
    def run(parts):
        env = {'PATH':'/usr/bin:/bin','HOME':'/worker-home','GIT_CONFIG_NOSYSTEM':'1',
               'GIT_CONFIG_GLOBAL':'/dev/null','GIT_NO_LAZY_FETCH':'1','GIT_NO_REPLACE_OBJECTS':'1',
               'GIT_TERMINAL_PROMPT':'0'}
        def bounded_output():resource.setrlimit(resource.RLIMIT_FSIZE,(4096,4096))
        with tempfile.TemporaryFile() as output:
            p = subprocess.run(['git', '--no-optional-locks', '-c', 'core.hooksPath=/dev/null',
                            '-c', 'core.fsmonitor=false', '-C', str(runner), *parts],
                           env=env, stdin=subprocess.DEVNULL, stdout=output,stderr=subprocess.DEVNULL,
                           timeout=10,preexec_fn=bounded_output)
            output.seek(0);data=output.read(4097)
        if p.returncode or len(data) >= 4096: raise ValueError('Git unavailable')
        return data
    call = call or run
    # Inspect config keys without following includes, before loading any user
    # helper. Do not run credential fill here: this gate must precede auth use.
    keys = call(['config','--local','--no-includes','--name-only','--list']).decode().splitlines()
    tracking_keys(keys, call)
    if call(['config','--local','--no-includes','--get','remote.origin.url']).strip() != b'https://github.com/aliercankonus/signal-desk-prediction.git':
        raise ValueError('remote scope')
    if call(['rev-parse','HEAD']).strip() != PIN.encode() or call(['status','--porcelain=v1','--untracked-files=all']):
        raise ValueError('runner HEAD/cleanliness')
    s = config.lstat()
    if not stat.S_ISREG(s.st_mode) or s.st_uid != 10000 or s.st_gid != 10000 or s.st_mode & 0o077 or s.st_size > 2048:
        raise PermissionError('Git config metadata')
    # The root-installed helper is mounted as an immutable file at this exact
    # path. Load only its constant template; importing it has no credential I/O.
    import importlib.util
    spec = importlib.util.spec_from_file_location('reviewed_worker_credential',HELPER_MODULE)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    fd = os.open(config, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as f:
        opened = os.fstat(f.fileno())
        if (opened.st_dev, opened.st_ino, opened.st_mode) != (s.st_dev,s.st_ino,s.st_mode):
            raise ValueError('Git config changed')
        data = f.read(2049)
    named = config.lstat()
    if (named.st_dev,named.st_ino,named.st_size,named.st_mtime_ns) != (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns):
        raise ValueError('Git config changed')
    if data != module.GITCONFIG.encode(): raise ValueError('Git helper configuration')
    return {'worker_owner_git':True,'credential_helper_configured':True}


def main():
    try:
        print(json.dumps(check(),sort_keys=True)); return 0
    except Exception as exc:
        code = str(exc) if isinstance(exc, PreflightBlocked) else 'OWNER_CONFIG_UNVERIFIED'
        print('WORKER_PREFLIGHT: BLOCKED CODE='+code); return 1


if __name__ == '__main__': raise SystemExit(main())
