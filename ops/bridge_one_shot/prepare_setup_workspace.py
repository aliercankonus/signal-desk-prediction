"""Operator-only fresh setup workspace; public source files, never secrets/runtime."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import time
import types

PUBLIC_PIN = '0fbf46053a74bad4a35ecb3d324b6decab530b83'
FILES = {
    'prepare_operator_spec.py': 'c1bc75f44a195ac2d34ac8000a983a9bbb6ab74369c212c96d5504f544697f8a',
    'install_operator_bootstrap.sh': 'ee29f7b42e36b79ca46e8516e0fa3b0a321b481b2c244edf4970f81564da638d',
}
ENV = {
    'PATH': '/usr/sbin:/sbin:/usr/bin:/bin', 'HOME': '/nonexistent', 'LC_ALL': 'C',
    'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null',
    'GIT_TERMINAL_PROMPT': '0', 'GIT_NO_LAZY_FETCH': '1',
    'GIT_NO_REPLACE_OBJECTS': '1', 'GIT_OPTIONAL_LOCKS': '0',
}
DEADLINE = None


class Stop(Exception):
    pass


def canonical(value):
    path = Path(value)
    if (not value.startswith('/') or value == '/' or str(path) != value or
            '..' in path.parts or len(value) > 512 or any(ord(c) < 32 for c in value)):
        raise Stop('INVALID_PATH')
    return path


def trusted(path, owner=0, private=False):
    for part in (path, *path.parents):
        info = part.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, owner) or
                info.st_mode & 0o022 or (part == path and private and info.st_mode & 0o077)):
            raise Stop('UNTRUSTED_PATH')


def git_read(store, args):
    remaining = 15 if DEADLINE is None else min(15, DEADLINE - time.monotonic())
    if remaining <= 0:
        raise Stop('PREPARATION_DEADLINE')
    child = subprocess.Popen(
        ['/usr/bin/git', '--git-dir=' + str(store), *args], env=ENV,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        data, _ = child.communicate(timeout=remaining)
        if child.returncode or len(data) > 32768:
            raise Stop('PUBLIC_SOURCE_READ_FAILED')
        return data
    finally:
        if child.poll() is None:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait(timeout=2)
        child.stdout.close()


def public_blob(store, name):
    # A fixed immutable ref, replacements/lazy fetch disabled, and size checked
    # before reading bytes; no worker checkout or mutable installed helper used.
    ref = PUBLIC_PIN + ':ops/bridge_one_shot/' + name
    size = git_read(store, ('cat-file', '-s', ref))
    if not size.strip().isdigit() or not 0 < int(size) <= 32768:
        raise Stop('PUBLIC_SOURCE_SIZE')
    blob = git_read(store, ('show', ref))
    if len(blob) != int(size) or hashlib.sha256(blob).hexdigest() != FILES[name]:
        raise Stop('PUBLIC_SOURCE_DIGEST')
    return blob


def exclude_current_mounts(boot, protected):
    ids = boot.command(['docker', 'ps', '-aq', '--no-trunc']).decode('ascii').splitlines()
    if len(ids) > 32 or len(set(ids)) != len(ids) or any(
            not re.fullmatch('[0-9a-f]{64}', value) for value in ids):
        raise Stop('DOCKER_INVENTORY_BOUND')
    for ident in ids:
        mounts = json.loads(boot.command([
            'docker', 'inspect', '--type', 'container', '--format', '{{json .Mounts}}', ident]))
        if not isinstance(mounts, list) or len(mounts) > 64:
            raise Stop('DOCKER_MOUNTS_INVALID')
        for mount in mounts:
            if not isinstance(mount, dict) or mount.get('Type') not in ('bind', 'volume', 'tmpfs'):
                raise Stop('DOCKER_MOUNTS_INVALID')
            canonical(mount.get('Destination', ''))
            if mount['Type'] == 'tmpfs':
                if mount.get('Source') not in ('', 'tmpfs'):
                    raise Stop('DOCKER_MOUNTS_INVALID')
                continue
            source = canonical(mount.get('Source', ''))
            if any(boot._overlap(source, path) for path in protected):
                raise Stop('CURRENT_MOUNT_OVERLAP')


def venv_metadata(value):
    # Read metadata only. Never execute a worker-owned interpreter or chmod it.
    result = {'path': value, 'status': 'UNPROVEN'}
    if not value:
        return result
    try:
        path = canonical(value)
        trusted(path, owner=10000)
        directory = path.lstat()
        config = (path / 'pyvenv.cfg').lstat()
        result.update(uid=directory.st_uid, gid=directory.st_gid,
                      mode=stat.S_IMODE(directory.st_mode))
        if (directory.st_uid == 10000 and stat.S_ISREG(config.st_mode) and
                config.st_uid == 10000 and 0 < config.st_size <= 8192):
            result['status'] = 'READY_METADATA_ONLY' if not directory.st_mode & 0o077 else 'PRIVATE_COPY_REVIEW_REQUIRED'
    except (OSError, ValueError, TypeError, Stop):
        pass
    return result


def prepare(source_value, parent_value, *, venv='', apply=False):
    global DEADLINE
    if os.geteuid() != 0:
        raise Stop('ROOT_REQUIRED')
    DEADLINE = time.monotonic() + 180
    source, parent = canonical(source_value), canonical(parent_value)
    trusted(source, private=True)
    trusted(parent.parent)
    if os.path.lexists(parent):
        raise Stop('DESTINATION_EXISTS_PRESERVE_STATE')
    if source == parent or source in parent.parents or parent in source.parents:
        raise Stop('SOURCE_DESTINATION_OVERLAP')
    blobs = {name: public_blob(source, name) for name in FILES}
    guide = types.ModuleType('reviewed_setup_guide')
    exec(compile(blobs['prepare_operator_spec.py'], '<reviewed-setup-guide>', 'exec'), guide.__dict__)
    # The already reviewed guide additionally checks the immutable bootstrap
    # consumer's exact size/SHA before loading its administrative helpers.
    boot = guide.load_consumer(str(source))
    boot.STAGING_DEADLINE = DEADLINE
    exclude_current_mounts(boot, (source, parent))
    venv_info = venv_metadata(venv)
    manifest = {
        'schema': 1, 'purpose': 'public-setup-workspace-only',
        'source': str(source), 'workspace': str(parent), 'source_pin': PUBLIC_PIN,
        'files': FILES, 'venv_metadata': venv_info,
        'runtime_authority': False, 'credential_provisioning': False,
        'mount_check': 'bounded-current-metadata-only-not-global-isolation-proof',
    }
    if not apply:
        print('WORKSPACE_PLAN: READY; no files created')
        print('OVERALL: NO-GO — public preparation only')
        return
    # All reads/provenance checks above. Every publication below is exclusive;
    # interruption preserves partial state, with no overwrite/retry/cleanup.
    boot._mkdir(parent, 0, 0)
    for name, blob in blobs.items():
        boot._write(parent / name, blob, 0, 0)
    boot._write(parent / 'setup-manifest.json', manifest, 0, 0)
    for name, digest in FILES.items():
        if hashlib.sha256((parent / name).read_bytes()).hexdigest() != digest:
            raise Stop('INSTALLED_DIGEST_MISMATCH_PRESERVE_STATE')
    directory = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    print('SETUP_WORKSPACE: PREPARED')
    print('GUIDE_INSTALLER: HASH_VERIFIED')
    print('VENV_PRIVATE_SOURCE: ' + venv_info['status'])
    print('SECRETS_AUTH_SERVICES: NOT_CREATED')
    print('OVERALL: NO-GO — public preparation only; enrollment not installed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--parent', required=True)
    parser.add_argument('--venv', default='')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        prepare(args.source, args.parent, venv=args.venv, apply=args.apply)
    except Stop as exc:
        print('STOP: ' + str(exc))
        return 1
    except Exception:
        print('STOP: UNVERIFIED_PREPARATION_STATE; preserve files; no retry')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
