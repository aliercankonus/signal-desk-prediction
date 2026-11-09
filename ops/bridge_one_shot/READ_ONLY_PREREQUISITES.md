# #41 first operator step: read-only prerequisite inventory

**Review-only, NOT RUN ON VPS.** Copy the single Bash block in its entirety into an independently approved root terminal. It is byte-for-byte `read_only_prereqs.sh` at this commit. It needs no installed helper, private spec, credentials, network download, or answers from Ali. It never creates a candidate record and never prompts for private paths. If an independently prepared, root-owned 0600 local candidate record already exists at the script's fixed private location, it reads at most 4096 bytes from a nonsymlinked private directory, rejects records older than seven days, and accepts only schema `1` with allowlisted `host` (source, runner, venv, private parent and root-only file paths), `container` (venv path), and `docker` (immutable image/exact container ID) fields. This is optional metadata, **not** a request to create or edit JSON; absent, stale, malformed, or unsafe records are ignored as UNPROVEN/NOT_CONFIGURED. Container paths are never used as host venv sources. A venv interpreter symlink is metadata, not runtime proof. An absent one-shot project is normal; an available retained image can be checked independently. Do not paste private paths, container identities, or Docker metadata into GitHub. PRESENT means metadata only, never GO. Unconfigured inputs are UNPROVEN rather than falsely reported as observed host absence; a specifically checked absent/untrusted candidate is MISSING. Root/session failures remain NO-GO. The manager must review the exact merged bytes before instructing an operator to run them.

```bash
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
LABEL = 'label=com.docker.compose.project=signal-desk-bridge-once'
# Optional operator-retained root-private metadata; the inventory NEVER creates it.
CANDIDATE_RECORD = '/root/.local/state/signal-desk/candidates.json'
ENV = dict(PATH='/usr/sbin:/sbin:/usr/bin:/bin', HOME='/nonexistent', LC_ALL='C',
           GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null',
           GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='never')
GATES = ('candidate_metadata', 'source', 'source_objects', 'runner', 'venv',
         'container_venv', 'interpreter', 'image',
         'project_containers', 'candidate_container', 'container_mounts',
         'private_parent', 'signer_key', 'signer_public',
         'root_readback', 'dependencies', 'image_internal_isolation',
         'manager_exclusive_invocation', 'persistent_worker', 'runtime_capability')


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
            raise LookupError('read-only command unavailable')
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


def canonical_path(value):
    return (isinstance(value, str) and 0 < len(value) <= 512 and value.startswith('/') and
            not any(ord(ch) < 32 for ch in value) and
            '..' not in pathlib.PurePosixPath(value).parts and
            str(pathlib.PurePosixPath(value)) == value)

def load_candidate_metadata(path=CANDIDATE_RECORD, *, owner=0, now=None):
    """Read only a bounded, recent, private local hint; never return its bytes or paths in status."""
    unavailable = ({}, 'retained metadata unavailable/untrusted/stale; ignored')
    if not pathlib.PurePosixPath(path).is_absolute() or not canonical_path(path):
        return unavailable
    try:
        leaf = pathlib.Path(path)
        for parent in (leaf.parent, *leaf.parent.parents):
            info = parent.lstat()
            if (not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, owner) or
                    info.st_mode & 0o022):
                return unavailable
        if leaf.parent.lstat().st_mode & 0o077:
            return unavailable
        before = leaf.lstat()
        current = time.time() if now is None else now
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != owner or
                before.st_mode & 0o077 or not 0 < before.st_size <= 4096 or
                not 0 <= current - before.st_mtime <= 7 * 86400):
            return unavailable
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            opened = os.fstat(fd)
            if (opened.st_dev, opened.st_ino, opened.st_mode, opened.st_uid,
                opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns) != (
                before.st_dev, before.st_ino, before.st_mode, before.st_uid,
                before.st_size, before.st_mtime_ns, before.st_ctime_ns):
                return unavailable
            raw = os.read(fd, 4097)
            after = os.fstat(fd)
            if (len(raw) != before.st_size or len(raw) > 4096 or
                    (after.st_size, after.st_mtime_ns, after.st_ctime_ns) !=
                    (before.st_size, before.st_mtime_ns, before.st_ctime_ns)):
                return unavailable
        finally:
            os.close(fd)
        def unique_pairs(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('duplicate metadata key')
                result[key] = value
            return result
        def no_constant(value):
            raise ValueError('nonstandard JSON constant')
        data = json.loads(raw.decode('utf-8'), object_pairs_hook=unique_pairs,
                          parse_constant=no_constant)
        if (not isinstance(data, dict) or data.get('schema') != 1 or
                type(data['schema']) is not int or set(data) - {'schema', 'host', 'container', 'docker'}):
            return unavailable
        allowed = {'host':{'source','runner','venv','private_parent','signer_key',
                           'signer_public','root_readback'},
                   'container':{'venv'}, 'docker':{'image','container'}}
        values = {}
        for section, fields in allowed.items():
            entries = data.get(section, {})
            if not isinstance(entries, dict) or set(entries) - fields:
                return unavailable
            for key, value in entries.items():
                if not isinstance(value, str) or not value or len(value) > 512:
                    return unavailable
                if section != 'docker' and not canonical_path(value):
                    return unavailable
                if section == 'docker' and not re.fullmatch(
                        'sha256:[0-9a-f]{64}' if key == 'image' else '[0-9a-f]{64}', value):
                    return unavailable
                values['container_venv' if section == 'container' else key] = value
        return values, 'retained candidate metadata parsed; host paths and IDs unverified'
    except FileNotFoundError:
        return {}, 'NOT_CONFIGURED: no retained local metadata'
    except (OSError, ValueError, TypeError, UnicodeError):
        return unavailable


def overlaps(left, right):
    """Canonical lexical host-path overlap in BOTH directions; no symlink resolution."""
    if not canonical_path(left) or not canonical_path(right):
        raise ValueError('noncanonical mount or protected path')
    a, b = pathlib.PurePosixPath(left), pathlib.PurePosixPath(right)
    return a == b or a in b.parents or b in a.parents


def inventory(inputs, run=bounded, candidate_state='NOT_CONFIGURED: no retained local metadata'):
    report = {gate: ('UNPROVEN', 'requires independent operator proof') for gate in GATES}
    missing = []
    def mark(name, status, detail):
        report[name] = (status, detail)
        if status == 'MISSING':
            missing.append(name)
    mark('candidate_metadata', 'UNPROVEN', candidate_state)
    container_venv = inputs.get('container_venv', '')
    mark('container_venv', 'UNPROVEN' if not container_venv or canonical_path(container_venv) else 'MISSING',
         'retained container path only; not a host venv or runtime proof' if container_venv and canonical_path(container_venv) else
         'invalid retained container path' if container_venv else
         'NOT_CONFIGURED: container path unverified; host source unknown')
    source = inputs.get('source', '')
    if not source:
        mark('source', 'UNPROVEN', 'NOT_CONFIGURED: protected bare store host path')
        mark('source_objects', 'UNPROVEN', 'host source NOT_CONFIGURED; objects uninspected')
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
        except (OSError, ValueError, TimeoutError, AssertionError, LookupError):
            mark('source', 'MISSING', 'bare store or object identity check failed')
            mark('source_objects', 'MISSING', 'pin absent/mismatch/timeout')
    runner = inputs.get('runner', '')
    if not runner:
        mark('runner', 'UNPROVEN', 'NOT_CONFIGURED: runner host path')
    elif not trusted(runner):
        mark('runner', 'MISSING', 'absent/untrusted/symlinked runner root')
    else:
        mark('runner', 'UNPROVEN', 'trusted directory only; HEAD/cleanliness and UID unverified')
    venv = inputs.get('venv', '')
    if not venv:
        mark('venv', 'UNPROVEN', 'host path NOT_CONFIGURED; container path is not a host source')
        mark('interpreter', 'UNPROVEN', 'host interpreter path NOT_CONFIGURED; not executed')
    elif not trusted(venv, worker=True):
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
            if stat.S_ISLNK(bi.st_mode):
                mark('interpreter', 'UNPROVEN', 'interpreter symlink metadata only; target/runtime not verified')
            else:
                mark('interpreter', 'UNPROVEN' if stat.S_ISREG(bi.st_mode) else 'MISSING',
                     'interpreter file metadata only; runtime not executed')
        except OSError:
            mark('venv', 'MISSING', 'venv metadata unavailable')
            mark('interpreter', 'MISSING', 'interpreter metadata unavailable')
    parent = inputs.get('private_parent', '')
    mark('private_parent', 'PRESENT' if parent and trusted(parent, private=True) else
         'MISSING' if parent else 'UNPROVEN',
         'trusted root-private parent metadata' if parent and trusted(parent, private=True) else
         'absent/untrusted/symlinked private parent candidate' if parent else
         'NOT_CONFIGURED: private parent host path')
    for gate in ('signer_key', 'signer_public', 'root_readback'):
        value = inputs.get(gate, '')
        mark(gate, 'PRESENT' if value and trusted(value, private=True, file=True) else
             'MISSING' if value else 'UNPROVEN',
             'root-private file metadata only; contents/authority UNPROVEN' if value and trusted(value, private=True, file=True) else
             'absent/untrusted/symlinked root-private file candidate' if value else
             'NOT_CONFIGURED: root-private file path')
    candidate_image = inputs.get('image', '')
    candidate_container = inputs.get('container', '')
    ids = []
    listed = False
    try:
        ids = run(['docker', 'ps', '-aq', '--no-trunc', '--filter', LABEL, '--format', '{{.ID}}']).decode('ascii').splitlines()
        if len(ids) > 8 or len(set(ids)) != len(ids) or any(
                not re.fullmatch('[0-9a-f]{64}', x) for x in ids):
            raise ValueError('ambiguous bounded project inventory')
        listed = True
        mark('project_containers', 'PRESENT' if ids else 'UNPROVEN',
             'bounded project IDs observed; not a persistent worker proof' if ids else
             'no project containers observed; installation NOT_CONFIGURED')
    except (OSError, ValueError, UnicodeError, TimeoutError, LookupError):
        mark('project_containers', 'UNPROVEN', 'bounded Docker project list unavailable/invalid')
        ids = []  # A failed list is not a claim of project absence.
    inspect_ids = list(ids)
    if candidate_container:
        if not re.fullmatch('[0-9a-f]{64}', candidate_container):
            mark('candidate_container', 'MISSING', 'invalid optional container ID')
        elif candidate_container not in inspect_ids:
            inspect_ids.append(candidate_container)
    else:
        mark('candidate_container', 'UNPROVEN', 'NOT_CONFIGURED: optional container ID')
    observed_images = set()
    protected = [x for x in (source, parent, inputs.get('signer_key', ''),
                             inputs.get('signer_public', ''), inputs.get('root_readback', '')) if x]
    mount_bad = False

    fmt = '{{.Image}}|{{.Config.User}}|{{json .Mounts}}|'
    for ident in inspect_ids:  # at most eight project IDs plus one explicit candidate
        try:
            raw = run(['docker', 'container', 'inspect', '--format', fmt, ident], limit=8192)
            image, user, rest = raw.decode('utf-8').split('|', 2)
            mounts, delimiter, tail = rest.rpartition('|')
            if (not delimiter or tail.strip() or not re.fullmatch('sha256:[0-9a-f]{64}', image) or
                    not user or len(mounts) > 8192):
                raise ValueError('container identity/metadata invalid')
            data = json.loads(mounts)
            if not isinstance(data, list) or len(data) > 32 or any(
                    not isinstance(m, dict) or not {'Source', 'Destination', 'Type'} <= set(m) or
                    m['Type'] not in ('bind', 'volume', 'tmpfs') or
                    not canonical_path(m['Destination']) or
                    (m['Type'] == 'tmpfs' and m['Source'] not in ('', 'tmpfs')) or
                    (m['Type'] != 'tmpfs' and not canonical_path(m['Source'])) for m in data):
                raise ValueError('mount metadata invalid')
            observed_images.add(image)
            if any(m['Type'] != 'tmpfs' and overlaps(m['Source'], p)
                   for m in data for p in protected):
                mount_bad = True
            if ident == candidate_container:
                mark('candidate_container', 'PRESENT', 'explicit container metadata only; project membership unverified')
        except (ValueError, UnicodeError):
            mount_bad = True  # Malformed source/identity is not a clean exclusion.
            if ident == candidate_container:
                mark('candidate_container', 'MISSING', 'optional container metadata invalid')
        except (OSError, TimeoutError, AssertionError, LookupError):
            if ident == candidate_container:
                mark('candidate_container', 'UNPROVEN', 'optional container inspection unavailable')
    mark('container_mounts', 'MISSING' if mount_bad else 'UNPROVEN',
         'overlap or malformed mount metadata' if mount_bad else
         'bounded mounts only; uninspected containers/global exclusion UNPROVEN')
    if candidate_image and not re.fullmatch('sha256:[0-9a-f]{64}', candidate_image):
        mark('image', 'MISSING', 'invalid optional immutable image ID')
    elif candidate_image and observed_images and any(x != candidate_image for x in observed_images):
        mark('image', 'MISSING', 'candidate differs from observed container image')
    elif len(observed_images) > 1:
        mark('image', 'MISSING', 'bounded project containers report differing images')
    else:
        selected = candidate_image or next(iter(observed_images), '')
        if not selected:
            mark('image', 'UNPROVEN', 'NOT_CONFIGURED: image ID; no observed container image')
        else:
            try:
                observed = run(['docker', 'image', 'inspect', '--format', '{{.Id}}', selected]).decode('ascii').strip()
                mark('image', 'PRESENT' if observed == selected else 'MISSING',
                     'immutable image ID matches metadata; contents UNPROVEN' if observed == selected else
                     'candidate/observed image identity mismatch')
            except (OSError, ValueError, UnicodeError, TimeoutError, AssertionError, LookupError):
                mark('image', 'MISSING' if candidate_image and listed else 'UNPROVEN',
                     'candidate image unavailable/mismatch' if candidate_image and listed else
                     'image availability unverified')
    return report, missing


def main():
    if os.geteuid() != 0:
        print('ROOT_METADATA: MISSING (use reviewed root terminal; no change made)')
        print('OVERALL: NO-GO')
        return
    try:
        values, candidate_state = load_candidate_metadata()
        report, missing = inventory(values, candidate_state=candidate_state)
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
```

After actual host output, use `OPERATOR_SEQUENCE_PROPOSAL.md` to decide only the missing protected source/private parents, image/venv/UID and distinct signer/worker credential provisioning. Runtime and scheduler are separately authorized.
