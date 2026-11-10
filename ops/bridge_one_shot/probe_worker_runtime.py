"""Operator-only, network-none worker capability probe; never enroll or dispatch."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import signal
import stat
import subprocess
import tempfile

ATTEMPT = 'issue41-cold-20261110-01'
STAGE_SOURCE = '674392d6cd87e1c440d1dc7eec916fcb6882b545'
RUNNER_PIN = 'e84021a786004456a12de9e25eae50d191da6cf1'
ADAPTER_PIN = 'eac843de7967d48cce56ee9a198750e98754a2de'
ENGINE = 'd0ae47d12190bb2b400e99181f4802fe291698924b92df7ca499b39834bb84f3'
PRESERVED = 'bd224f9ddf7f2985ae11659e2cac13d33b47403ab24bded1e2cef37de4017ac3'
PLAN_KEYS = ('attempt', 'bundle', 'source', 'merge', 'image', 'uid', 'gid',
    'runner', 'state', 'auth', 'context', 'home', 'venv', 'inbox', 'signer_token',
    'signer_key', 'signer_public', 'signer_policy', 'signer_state_root',
    'overall_seconds', 'journal_parent')
PROBE = ATTEMPT + '-runtime-probe-01'
TEST_PYTHON = '/opt/data/signal-desk-tooling/venvs/issue26-recovery-python314-20261030/bin/python'
IMAGE_PYTHON = '/opt/hermes/.venv/bin/python'
HOST_ENV = {'PATH': '/usr/bin:/bin', 'HOME': '/nonexistent', 'LC_ALL': 'C',
            'DOCKER_HOST': 'unix:///var/run/docker.sock', 'DOCKER_CONFIG': '/nonexistent'}
TMPFS = {'/worker-home': 'rw,noexec,nosuid,nodev,size=16m,mode=0700,uid=10000,gid=10000',
         '/tmp': 'rw,noexec,nosuid,nodev,size=32m,mode=1777',
         '/opt/data': 'rw,noexec,nosuid,nodev,size=1m,mode=0755',
         '/home': 'rw,noexec,nosuid,nodev,size=1m,mode=0755',
         '/root': 'rw,noexec,nosuid,nodev,size=1m,mode=0700'}
ENV_NAMES = set('PATH PYTHONUNBUFFERED PYTHONDONTWRITEBYTECODE PLAYWRIGHT_BROWSERS_PATH '
                'HERMES_RUNTIME_DIR HERMES_PYTHON CC CXX HERMES_WEB_DIST HERMES_TUI_DIR '
                'HERMES_HOME HERMES_WRITE_SAFE_ROOT XDG_RUNTIME_DIR HOME'.split())

# Executed only inside the operator-created container. No Hermes import, auth,
# provider call, GitHub request or test-suite repetition. All subprocesses bounded.
WORKER = r'''
import json,os,subprocess,shutil
r={'schema':1,'worker_identity':os.getuid()==10000 and os.getgid()==10000}
def call(a):
    try:
        p=subprocess.run(a,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=12)
        return p.stdout if p.returncode==0 and len(p.stdout)<4096 else None
    except Exception: return None
for name in ('git','gh','hermes'): r[name+'_available']=shutil.which(name) is not None
git=['git','--no-optional-locks','-c','core.hooksPath=/dev/null','-c','credential.helper=',
     '-c','core.fsmonitor=false','-c','core.untrackedCache=false','-C','/workspace/runner']
r['runner_head']=call(git+['rev-parse','HEAD'])==b'e84021a786004456a12de9e25eae50d191da6cf1\n'
r['runner_clean']=call(git+['status','--porcelain=v1','--untracked-files=all'])==b''
v=call(['TEST_PYTHON','-I','-B','-c',
        'import sys,importlib.metadata,json;print(json.dumps([".".join(map(str,sys.version_info[:3])),importlib.metadata.version("pytest")]))'])
try: r['test_versions']=json.loads(v)
except Exception: r['test_versions']=None
r['versions_match']=r['test_versions']==['3.14.9','8.3.3']
r['capability_pass']=all(r[k] for k in ('worker_identity','git_available','gh_available','hermes_available','runner_head','runner_clean','versions_match'))
print(json.dumps(r,sort_keys=True,separators=(',',':')))
'''.replace('TEST_PYTHON', TEST_PYTHON)


class Stop(Exception):
    pass


def root_dir(folder):
    for p in (folder, *folder.parents):
        s = p.lstat()
        if not stat.S_ISDIR(s.st_mode) or s.st_uid != 0 or s.st_mode & 0o022:
            raise Stop('ROOT_ANCESTRY')
    if folder.stat().st_mode & 0o077: raise Stop('PRIVATE_WORKSPACE')


def read_root(file, limit=32768):
    s = file.lstat()
    if not stat.S_ISREG(s.st_mode) or s.st_uid != 0 or s.st_mode & 0o077 or not 0 < s.st_size <= limit:
        raise Stop('ROOT_INPUT_METADATA')
    fd = os.open(file, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    with os.fdopen(fd, 'rb') as f:
        t = os.fstat(f.fileno())
        data = f.read(limit + 1)
    if (s.st_dev, s.st_ino, s.st_size) != (t.st_dev, t.st_ino, len(data)): raise Stop('ROOT_INPUT_CHANGED')
    return data


def exclusive(file, data):
    fd = os.open(file, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump(data, f, sort_keys=True); f.write('\n'); f.flush(); os.fsync(f.fileno())
    fd = os.open(file.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try: os.fsync(fd)
    finally: os.close(fd)


def inputs(value):
    if os.geteuid() != 0: raise Stop('ROOT_REQUIRED')
    w = Path(value)
    if not w.is_absolute() or str(w) != value or '..' in w.parts: raise Stop('WORKSPACE_PATH')
    root_dir(w)
    setup = json.loads(read_root(w/'setup-manifest.json'))
    cold = json.loads(read_root(w/'private-inputs-receipt.json'))
    raw = read_root(w/(ATTEMPT+'-bootstrap-spec.json'))
    cfg = json.loads(raw)
    if hashlib.sha256(read_root(w/(ATTEMPT+'-bootstrap.py'))).hexdigest() != PRESERVED:
        raise Stop('PRESERVED_BOOTSTRAP')
    stage = json.loads(read_root(w/(ATTEMPT+'-staging-receipt.json')))
    plan = json.loads(read_root(w/(ATTEMPT+'-operator-plan.json')))
    if (setup.get('schema') != 1 or setup.get('workspace') != value or
        setup.get('purpose') != 'public-setup-workspace-only' or setup.get('runtime_authority') is not False or
        cold.get('purpose') != 'unused-cold-inputs-only' or cold.get('repo') != 'aliercankonus/signal-desk-prediction' or
        cold.get('activation') is not False or cold.get('worker_credentials_installed') is not False or
        cold.get('provider_authentication') is not False or cold.get('task_authority') is not False or
        stage.get('schema') != 1 or stage.get('attempt') != ATTEMPT or stage.get('source_commit') != STAGE_SOURCE or
        stage.get('original_spec_sha256') != hashlib.sha256(raw).hexdigest() or
        stage.get('preserved_bootstrap_sha256') != PRESERVED or stage.get('completion_engine_sha256') != ENGINE or
        stage.get('runner_pin') != RUNNER_PIN or stage.get('adapter_pin') != ADAPTER_PIN or
        stage.get('activation') is not False or stage.get('worker_credentials_installed') is not False or
        stage.get('original_spec_start') != cfg.get('start') or
        cfg.get('attempt') != ATTEMPT or cfg.get('merge') != ADAPTER_PIN or
        cfg.get('uid') != 10000 or cfg.get('gid') != 10000 or
        cfg.get('source') != setup.get('source') or cfg.get('test_python') != TEST_PYTHON or
        cfg.get('python_version') != '3.14.9' or cfg.get('pytest_version') != '8.3.3' or
        cfg.get('runner') != str(w/(ATTEMPT+'-runner')) or
        cfg.get('image') != cold.get('image') or cfg.get('venv') != setup.get('venv_metadata', {}).get('path') or
        set(plan) != set(PLAN_KEYS) or any(k not in cfg or cfg[k] != v for k, v in plan.items())):
        raise Stop('STAGING_PROVENANCE')
    if not re.fullmatch('sha256:[0-9a-f]{64}', cfg['image']): raise Stop('IMAGE_ID')
    for key in ('runner', 'venv'):
        p = Path(cfg[key]); s = p.lstat()
        if not p.is_absolute() or str(p) != cfg[key] or '..' in p.parts or any(parent.is_symlink() for parent in (p, *p.parents)):
            raise Stop('MOUNT_PATH')
        if not stat.S_ISDIR(s.st_mode) or s.st_uid != 10000 or s.st_gid != 10000 or stat.S_IMODE(s.st_mode) != 0o700:
            raise Stop('WORKER_DIRECTORY_METADATA')
        if any(c in str(p) for c in ',\n\r\0'): raise Stop('MOUNT_PATH')
    return w, cfg


def docker(args, timeout):
    # Never print captured data/errors: only the caller's closed result schema.
    def limit_output(): resource.setrlimit(resource.RLIMIT_FSIZE, (32768, 32768))
    with tempfile.TemporaryFile() as output:
        p = subprocess.run(['/usr/bin/docker', *args], env=HOST_ENV, stdin=subprocess.DEVNULL,
                           stdout=output, stderr=subprocess.DEVNULL, timeout=timeout, preexec_fn=limit_output)
        output.seek(0); raw = output.read(32769)
    if p.returncode != 0 or len(raw) >= 32768: raise Stop('DOCKER_COMMAND')
    return raw


def create_args(cfg):
    args = ['create', '--pull=never', '--name', PROBE, '--label', 'signal-desk.capability='+PROBE,
            '--network=none', '--user=10000:10000', '--read-only', '--cap-drop=ALL',
            '--security-opt=no-new-privileges', '--pids-limit=64', '--memory=512m', '--cpus=1',
            '--restart=no', '--ipc=none', '--workdir=/workspace/runner',
            '--entrypoint='+IMAGE_PYTHON]
    for target, flags in TMPFS.items(): args += ['--tmpfs', target+':'+flags]
    for source, target in ((cfg['runner'], '/workspace/runner'), (cfg['venv'], str(Path(TEST_PYTHON).parent.parent))):
        args += ['--mount', 'type=bind,src='+source+',dst='+target+',readonly,bind-propagation=rprivate']
    env = {'HOME': '/worker-home', 'HERMES_HOME': '/worker-home', 'XDG_RUNTIME_DIR': '/worker-home',
           'HERMES_RUNTIME_DIR': '/worker-home', 'HERMES_WRITE_SAFE_ROOT': '/worker-home',
           'PATH': str(Path(TEST_PYTHON).parent)+':/opt/hermes/.venv/bin:/usr/local/bin:/usr/bin:/bin',
           'PYTHONDONTWRITEBYTECODE': '1', 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null',
           'GIT_TERMINAL_PROMPT': '0', 'GIT_NO_LAZY_FETCH': '1', 'GIT_NO_REPLACE_OBJECTS': '1',
           'HTTP_PROXY': '', 'HTTPS_PROXY': '', 'ALL_PROXY': ''}
    for key, value in env.items(): args += ['--env', key+'='+value]
    return args + [cfg['image'], '-I', '-B', '-c', WORKER]


FIELDS = ('.Id', '.Image', '.Config.User', '.Config.Labels', '.HostConfig.NetworkMode',
          '.HostConfig.ReadonlyRootfs', '.HostConfig.CapDrop', '.HostConfig.SecurityOpt',
          '.HostConfig.Tmpfs', '.Mounts', '.State.Running', '.State.ExitCode',
          '.HostConfig.Privileged', '.HostConfig.PidMode', '.HostConfig.IpcMode',
          '.HostConfig.PidsLimit', '.HostConfig.Memory', '.HostConfig.NanoCpus',
          '.HostConfig.RestartPolicy.Name', '.Config.Entrypoint', '.Config.Cmd')
FORMAT = '\n'.join('{{json '+field+'}}' for field in FIELDS)


def inspect(call, cid, cfg):
    lines = call(['inspect', '--type=container', '--format', FORMAT, cid], 8).decode().splitlines()
    if len(lines) != len(FIELDS): raise Stop('CONTAINER_INSPECTION')
    d = dict(zip(FIELDS, map(json.loads, lines)))
    expected = {'.Id': cid, '.Image': cfg['image'], '.Config.User': '10000:10000',
                '.Config.Labels': {'signal-desk.capability': PROBE}, '.HostConfig.NetworkMode': 'none',
                '.HostConfig.ReadonlyRootfs': True, '.HostConfig.CapDrop': ['ALL'],
                '.HostConfig.SecurityOpt': ['no-new-privileges'], '.HostConfig.Tmpfs': TMPFS,
                '.HostConfig.Privileged': False, '.HostConfig.PidMode': '', '.HostConfig.IpcMode': 'none',
                '.HostConfig.PidsLimit': 64, '.HostConfig.Memory': 536870912, '.HostConfig.NanoCpus': 1000000000,
                '.HostConfig.RestartPolicy.Name': 'no', '.Config.Entrypoint': [IMAGE_PYTHON],
                '.Config.Cmd': ['-I', '-B', '-c', WORKER]}
    # Image labels may exist; require our exclusive label and no other container
    # can have the recorded ID. Config labels never confer task authority.
    labels = d['.Config.Labels']
    if not isinstance(labels, dict) or labels.get('signal-desk.capability') != PROBE: raise Stop('CONTAINER_IDENTITY')
    expected.pop('.Config.Labels')
    if any(d[k] != v for k, v in expected.items()): raise Stop('CONTAINER_IDENTITY')
    binds = [m for m in d['.Mounts'] if m.get('Type') == 'bind']
    wanted = {(cfg['runner'], '/workspace/runner'), (cfg['venv'], str(Path(TEST_PYTHON).parent.parent))}
    if (len(binds) != 2 or {(m.get('Source'), m.get('Destination')) for m in binds} != wanted or
            any(m.get('RW') is not False or m.get('Propagation') != 'rprivate' for m in binds) or
            any(m.get('Type') not in ('bind', 'tmpfs') or
                (m.get('Type') == 'tmpfs' and m.get('Destination') not in TMPFS) for m in d['.Mounts'])):
        raise Stop('CONTAINER_MOUNTS')
    return d


def validate_result(raw):
    r = json.loads(raw)
    flags = ('worker_identity', 'git_available', 'gh_available', 'hermes_available', 'runner_head', 'runner_clean', 'versions_match', 'capability_pass')
    if (set(r) != {'schema', 'test_versions', *flags} or r['schema'] != 1 or
            any(type(r[k]) is not bool for k in flags) or
            r['test_versions'] is not None and (not isinstance(r['test_versions'], list) or
                len(r['test_versions']) != 2 or any(not isinstance(v, str) or not re.fullmatch('[0-9.]{1,32}', v) for v in r['test_versions'])) or
            r['versions_match'] != (r['test_versions'] == ['3.14.9', '8.3.3']) or
            r['capability_pass'] != all(r[k] for k in flags[:-1])):
        raise Stop('WORKER_RESULT')
    return r


def probe(w, cfg, *, apply=False, call=docker):
    if not apply:
        print('PROBE: PREPARED_ONLY; no Docker invocation'); return
    # A prior intent, even after successful cleanup, is never an automatic retry.
    intent = w/(PROBE+'-intent.json')
    if any(os.path.lexists(w/(PROBE+suffix)) for suffix in ('-intent.json', '-container.json', '-receipt.json')):
        raise Stop('PRIOR_PROBE_PRESERVE')
    # Read names/immutable ID/declared volume destinations; never environment values.
    fmt = '{{.Id}}\n{{json .Config.Volumes}}\n{{range .Config.Env}}{{println (index (split . "=") 0)}}{{end}}'
    rows = call(['image', 'inspect', '--format', fmt, cfg['image']], 10).decode('ascii').splitlines()
    if rows and rows[-1] == '': rows.pop()
    if (len(rows) < 2 or rows[0] != cfg['image'] or not set(json.loads(rows[1]) or {}).issubset(TMPFS) or
            len(rows[2:]) != len(set(rows[2:])) or not set(rows[2:]).issubset(ENV_NAMES)):
        raise Stop('IMAGE_METADATA_REVIEW')
    exclusive(intent, {'schema': 1, 'probe': PROBE, 'image': cfg['image'], 'task_authority': False})
    cid = None; trusted = False; cleaned = False; result = None; failed = False
    try:
        raw = call(create_args(cfg), 20).decode().strip()
        if not re.fullmatch('[0-9a-f]{64}', raw): raise Stop('CREATE_ID_UNCERTAIN')
        cid = raw
        exclusive(w/(PROBE+'-container.json'), {'schema': 1, 'id': cid, 'image': cfg['image']})
        inspect(call, cid, cfg); trusted = True
        output = call(['start', '--attach', cid], 75)
        state = inspect(call, cid, cfg)
        if state['.State.Running'] is not False or state['.State.ExitCode'] != 0: raise Stop('WORKER_EXIT')
        result = validate_result(output)
    except (Exception, KeyboardInterrupt):
        failed = True
    finally:
        # Only a recorded and fully verified ID may be stopped/removed. A lost
        # create response or identity mismatch is preserved, never guessed/adopted.
        if trusted:
            state = inspect(call, cid, cfg)
            if state['.State.Running']:
                call(['kill', '--signal=KILL', cid], 8)
                state = inspect(call, cid, cfg)
            if state['.State.Running'] is not False: raise Stop('CLEANUP_RUNNING_PRESERVE')
            call(['rm', cid], 8)
            remaining = call(['ps', '-aq', '--no-trunc', '--filter', 'id='+cid], 8).strip()
            if remaining: raise Stop('CLEANUP_UNVERIFIED')
            cleaned = True
        exclusive(w/(PROBE+'-receipt.json'), {'schema': 1, 'probe': PROBE, 'container_id': cid,
                  'cleanup_verified': cleaned, 'result': result, 'interrupted_or_error': failed,
                  'credentials_installed': False, 'task_authority': False})
    if failed or not cleaned: raise Stop('PROBE_INCOMPLETE_PRESERVE')
    print('WORKER_RUNTIME: '+('CAPABILITY_PASS' if result['capability_pass'] else 'BLOCKED'))
    for key in ('worker_identity', 'runner_head', 'runner_clean', 'git_available', 'gh_available', 'hermes_available', 'versions_match'):
        print(key.upper()+': '+('PASS' if result[key] else 'FAIL'))
    print('PROBE_CONTAINER: EXACT_ID_REMOVAL_VERIFIED')
    print('CREDENTIALS_AUTH_SERVICES: UNTOUCHED')
    print('OVERALL: NO-GO — capability only; isolation/manager authority and enrollment remain separate')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workspace', required=True); p.add_argument('--probe', action='store_true')
    a = p.parse_args()
    previous = signal.getsignal(signal.SIGTERM)
    def interrupted(*_): raise InterruptedError()
    signal.signal(signal.SIGTERM, interrupted)
    try:
        w, cfg = inputs(a.workspace); probe(w, cfg, apply=a.probe); return 0
    except (Exception, KeyboardInterrupt) as e:
        code = str(e) if isinstance(e, Stop) else 'PRESERVE_STATE'
        print('STOP: WORKER_RUNTIME_PROBE '+code+'; preserve files; no retry or cleanup')
        return 1
    finally: signal.signal(signal.SIGTERM, previous)


if __name__ == '__main__': raise SystemExit(main())
