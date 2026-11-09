# REVIEW-ONLY, standalone root-terminal block. No installed helper or spec required.
# Paste the complete block in the root terminal ONLY after separate operator review.
(
set +x
umask 077
PATH=/usr/sbin:/sbin:/usr/bin:/bin
export PATH
unset BASH_ENV ENV PYTHONPATH PYTHONHOME
/usr/bin/env -i PATH="$PATH" HOME=/nonexistent LC_ALL=C /usr/bin/python3 -I -B - <<'PY'
import json, os, pathlib, re, selectors, signal, stat, subprocess, time

MERGE = '1899a7e3023a2c30e9356414bc85a077804b5d0f'
BOOTSTRAP = '665698113fcd7d8f7d10a75ee42f67d8a2131166'
ADAPTER = 'eac843de7967d48cce56ee9a198750e98754a2de'
RUNNER = 'e84021a786004456a12de9e25eae50d191da6cf1'
REQUIREMENTS = '58f90369318da1e7ab651447080f06bb80c361a4a0109d79eca4762aba8bf97d'
# Previously reported development interpreter path: candidate, NOT a host assertion.
VENV_CANDIDATE = '/opt/data/signal-desk-tooling/venvs/issue26-recovery-python314-20261030'
LABEL = 'label=com.docker.compose.project=signal-desk-bridge-once'
ENV = dict(PATH='/usr/sbin:/sbin:/usr/bin:/bin', HOME='/nonexistent', LC_ALL='C',
           GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null',
           GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='never')
GATES = ('source', 'source_objects', 'runner', 'venv', 'interpreter', 'image',
         'container_mounts', 'private_parent', 'signer_key', 'signer_public',
         'root_readback', 'dependencies', 'image_internal_isolation',
         'manager_exclusive_invocation', 'persistent_worker', 'runtime_capability')


def ask(label):
    # These are optional PATHS/IDs, never credential contents; stdin is the Python source.
    try:
        with open('/dev/tty', 'r+') as tty:
            tty.write(label + ' (blank = NOT_CONFIGURED): '); tty.flush()
            ready, _, _ = __import__('select').select([tty], [], [], 30)
            if not ready:
                return ''
            value = tty.readline(513).rstrip('\n')
            return value if len(value) <= 512 else ''
    except OSError:
        return ''


def trusted(value, *, private=False, file=False, worker=False):
    if (not value or len(value) > 512 or any(ord(c) < 32 for c in value) or
            not value.startswith('/') or '..' in pathlib.Path(value).parts or
            str(pathlib.Path(value)) != value or value == '/'):
        return False
    path = pathlib.Path(value)
    try:
        leaf = path.lstat()
        worker_uid = leaf.st_uid if worker else 0
        for ancestor in (path.parent if file else path, *((path.parent if file else path).parents)):
            info = ancestor.lstat()  # never resolve a symlink
            if (not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, worker_uid) or
                    info.st_mode & 0o022):
                return False
        info = leaf
        if file:
            return (stat.S_ISREG(info.st_mode) and info.st_uid == 0 and
                    not info.st_mode & 0o077 and 0 < info.st_size <= 8192 and
                    (not private or not path.parent.lstat().st_mode & 0o077))
        return stat.S_ISDIR(info.st_mode) and (not private or not info.st_mode & 0o077)
    except (OSError, ValueError):
        return False


def bounded(argv, *, limit=4096, seconds=6):
    # Explicit allowlist: no exec/run/up/login, shell, credential helper, full inspect.
    git = (len(argv) >= 3 and argv[0] == 'git' and argv[1].startswith('--git-dir=/') and
           (argv[2:] == ['rev-parse', '--is-bare-repository'] or
            (len(argv) == 5 and argv[2:4] == ['cat-file', '-t'] and
             argv[4] in (MERGE, BOOTSTRAP, ADAPTER, RUNNER)) or
            (len(argv) == 6 and argv[2:4] == ['merge-base', '--is-ancestor'] and
             (argv[4], argv[5]) in ((BOOTSTRAP, MERGE), (ADAPTER, MERGE), (RUNNER, ADAPTER)))))
    docker = (argv == ['docker', 'ps', '-aq', '--no-trunc', '--filter', LABEL, '--format', '{{.ID}}'] or
              (len(argv) == 6 and argv[:4] == ['docker', 'container', 'inspect', '--format'] and
               argv[4] == '{{.Image}}|{{.Config.User}}|{{json .Mounts}}|' and
               bool(re.fullmatch('[0-9a-f]{64}', argv[5]))) or
              (len(argv) == 6 and argv[:5] == ['docker', 'image', 'inspect', '--format', '{{.Id}}'] and
               bool(re.fullmatch('sha256:[0-9a-f]{64}', argv[5]))))
    if not (git or docker):
        raise ValueError('command not in read-only inventory allowlist')
    executable = {'git':'/usr/bin/git', 'docker':'/usr/bin/docker'}[argv[0]]
    child = subprocess.Popen([executable, *argv[1:]], stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             env=ENV, start_new_session=True)
    deadline = time.monotonic() + seconds
    out = bytearray(); selector = selectors.DefaultSelector()
    try:
        selector.register(child.stdout, selectors.EVENT_READ)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('command timeout')
            for key, _ in selector.select(min(.1, remaining)):
                part = os.read(key.fd, min(1024, limit + 1 - len(out)))
                if not part:
                    selector.unregister(key.fileobj)
                else:
                    out.extend(part)
                    if len(out) > limit:
                        raise ValueError('command output bound')
        if child.wait(timeout=max(.001, deadline - time.monotonic())):
            raise ValueError('command failed')
        return bytes(out)
    finally:
        selector.close()
        if child.poll() is None:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait(timeout=2)
        child.stdout.close()


def inventory(inputs, run=bounded):
    report = {gate: ('UNPROVEN', 'requires independent operator proof') for gate in GATES}
    missing = []
    def mark(name, status, detail):
        report[name] = (status, detail)
        if status == 'MISSING':
            missing.append(name)
    source = inputs.get('source', '')
    if not source:
        mark('source', 'MISSING', 'NOT_CONFIGURED: protected bare store path')
        mark('source_objects', 'MISSING', 'requires protected source')
    elif not trusted(source, private=True):
        mark('source', 'MISSING', 'absent/untrusted/symlinked source')
        mark('source_objects', 'MISSING', 'source unavailable')
    else:
        try:
            git = ['git', '--git-dir=' + source]
            assert run(git + ['rev-parse', '--is-bare-repository']) == b'true\n'
            for pin in (MERGE, BOOTSTRAP, ADAPTER, RUNNER):
                assert run(git + ['cat-file', '-t', pin]) == b'commit\n'
            for older, newer in ((BOOTSTRAP, MERGE), (ADAPTER, MERGE), (RUNNER, ADAPTER)):
                assert run(git + ['merge-base', '--is-ancestor', older, newer]) == b''
            # Commit identity only; do not load/execute a checkout or read private files.
            mark('source', 'PRESENT', 'trusted private bare store metadata')
            mark('source_objects', 'PRESENT', 'all four exact commit objects')
        except (OSError, ValueError, TimeoutError, AssertionError):
            mark('source', 'MISSING', 'bare store or object identity check failed')
            mark('source_objects', 'MISSING', 'pin absent/mismatch/timeout')
    runner = inputs.get('runner', '')
    if not runner:
        mark('runner', 'MISSING', 'NOT_CONFIGURED: runner candidate path')
    elif not trusted(runner):
        mark('runner', 'MISSING', 'absent/untrusted/symlinked runner root')
    else:
        mark('runner', 'UNPROVEN', 'trusted directory only; HEAD/cleanliness and UID unverified')
    venv = inputs.get('venv', '') or VENV_CANDIDATE
    if not trusted(venv, worker=True):
        mark('venv', 'MISSING', 'candidate absent/untrusted/symlinked; verify host venv source')
        mark('interpreter', 'MISSING', 'candidate venv unavailable')
    else:
        cfg = pathlib.Path(venv) / 'pyvenv.cfg'
        binary = pathlib.Path(venv) / 'bin/python'
        try:
            ci, bi = cfg.lstat(), binary.lstat()
            # A Python binary may be a symlink in a normal venv: do not follow it as root.
            if stat.S_ISREG(ci.st_mode) and 0 < ci.st_size <= 8192:
                mark('venv', 'PRESENT', 'candidate venv metadata only; worker ownership UNPROVEN')
            else:
                mark('venv', 'MISSING', 'venv config type/size mismatch')
            mark('interpreter', 'UNPROVEN' if stat.S_ISREG(bi.st_mode) else 'MISSING',
                 'candidate interpreter metadata only; not executed')
        except OSError:
            mark('venv', 'MISSING', 'venv metadata unavailable')
            mark('interpreter', 'MISSING', 'interpreter metadata unavailable')
    parent = inputs.get('private_parent', '')
    mark('private_parent', 'PRESENT' if parent and trusted(parent, private=True) else 'MISSING',
         'trusted root-private parent metadata' if parent and trusted(parent, private=True) else
         'NOT_CONFIGURED or absent/untrusted/symlinked private parent')
    for gate in ('signer_key', 'signer_public', 'root_readback'):
        value = inputs.get(gate, '')
        mark(gate, 'PRESENT' if value and trusted(value, private=True, file=True) else 'MISSING',
             'root-private file metadata only; contents/authority UNPROVEN' if value and trusted(value, private=True, file=True) else
             'NOT_CONFIGURED or absent/untrusted/symlinked root-private file')
    try:
        ids = run(['docker', 'ps', '-aq', '--no-trunc', '--filter', LABEL, '--format', '{{.ID}}']).decode('ascii').splitlines()
        if len(ids) > 8 or any(not re.fullmatch('[0-9a-f]{64}', x) for x in ids):
            raise ValueError('ambiguous project container inventory')
        if len(ids) != 1:
            mark('image', 'MISSING', 'no unique existing project container/image identity')
            mark('container_mounts', 'UNPROVEN', 'no unique existing project container; mount exclusions unverified')
        else:
            # Whitelisted format: never request Config.Env, full inspect or output raw mount sources.
            fmt = '{{.Image}}|{{.Config.User}}|{{json .Mounts}}|'
            raw = run(['docker', 'container', 'inspect', '--format', fmt, ids[0]], limit=8192)
            image, user, mounts, _ = raw.decode('utf-8').split('|', 3)
            if not re.fullmatch('sha256:[0-9a-f]{64}', image) or not user or len(mounts) > 8192:
                raise ValueError('image/user metadata invalid')
            data = json.loads(mounts)
            if not isinstance(data, list) or len(data) > 32 or any(not isinstance(x, dict) or
                    not {'Source', 'Destination', 'Type'} <= set(x) for x in data):
                raise ValueError('mount metadata invalid')
            observed = run(['docker', 'image', 'inspect', '--format', '{{.Id}}', image]).decode().strip()
            mark('image', 'PRESENT' if observed == image else 'MISSING',
                 'immutable image ID matches inspect' if observed == image else 'image ID mismatch')
            protected = [x for x in (source, inputs.get('private_parent', '')) if x]
            overlap = any(m.get('Type') == 'bind' and any(
                m.get('Source') == p or str(m.get('Source', '')).startswith(p.rstrip('/') + '/')
                for p in protected) for m in data)
            mark('container_mounts', 'MISSING' if overlap else 'UNPROVEN',
                 'protected source/parent overlap' if overlap else 'mount exclusion needs actual host review')
    except (OSError, ValueError, UnicodeError, TimeoutError, AssertionError):
        mark('image', 'MISSING', 'Docker inventory unavailable/invalid/timeout')
        mark('container_mounts', 'UNPROVEN', 'Docker mounts not independently inspected')
    return report, missing


def main():
    if os.geteuid() != 0:
        print('ROOT_METADATA: MISSING (use reviewed root terminal; no change made)')
        return
    labels = {'source':'Optional existing protected bare store path',
              'runner':'Optional existing runner root path',
              'venv':'Optional inspected venv host path (blank checks one reported candidate)',
              'private_parent':'Optional existing root-private setup parent',
              'signer_key':'Optional existing root-only signing key path (metadata only)',
              'signer_public':'Optional existing root-only public verifier path (metadata only)',
              'root_readback':'Optional existing root-only readback file path (metadata only)'}
    values = {key: ask(label) for key, label in labels.items()}
    try:
        report, missing = inventory(values)
        for name in GATES:
            status, reason = report[name]
            print(name.upper() + ': ' + status + ' — ' + reason)
        print('MISSING_PREREQUISITES: ' + (', '.join(missing) if missing else 'none in metadata only; independent proof still required'))
        print('OVERALL: NO-GO — file presence is not authority, isolation or runtime capability')
    except Exception:
        # Do not reveal exception text: it may contain a private host path.
        print('INVENTORY: UNPROVEN — bounded read failed; preserve host state')
        print('OVERALL: NO-GO')

if __name__ == '__main__':
    main()
PY
)
# REVIEW ONLY: the subshell ended; no VPS change, no credentials read, no GO.
