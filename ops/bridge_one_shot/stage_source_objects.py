"""Operator-only public object preparation; never stages/starts the worker."""
import argparse
import os
from pathlib import Path
import selectors
import signal
import stat
import subprocess
import time


SOURCE = 'd21e19d7be85f9bf402e42b6f130846e022eb5e4'
URL = 'https://github.com/aliercankonus/signal-desk-prediction.git'
PINS = (
    '665698113fcd7d8f7d10a75ee42f67d8a2131166',
    'eac843de7967d48cce56ee9a198750e98754a2de',
    'e84021a786004456a12de9e25eae50d191da6cf1',
    '1899a7e3023a2c30e9356414bc85a077804b5d0f',
    SOURCE,
)
ENV = {
    'PATH': '/usr/bin:/bin', 'HOME': '/nonexistent', 'LC_ALL': 'C',
    'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null',
    'GIT_TERMINAL_PROMPT': '0', 'GIT_ASKPASS': '/bin/false',
    'SSH_ASKPASS': '/bin/false', 'GIT_NO_LAZY_FETCH': '1',
    'GIT_NO_REPLACE_OBJECTS': '1',
}
OPTIONS = (
    '-c', 'credential.helper=', '-c', 'http.extraHeader=',
    '-c', 'core.hooksPath=/dev/null', '-c', 'gc.auto=0',
    '-c', 'maintenance.auto=false', '-c', 'protocol.ext.allow=never',
    '-c', 'protocol.ssh.allow=never', '-c', 'protocol.file.allow=never',
)
FETCH = (
    'fetch', '--no-tags', '--no-write-fetch-head', '--no-recurse-submodules',
    '--no-auto-maintenance', URL, SOURCE,
)
# Do not let local includes, URL rewrites or scoped authentication attach private
# identities to this public-only transfer. Values are never printed or requested.
UNSAFE_CONFIG = r'^(include\.|includeif\.|credential\.|url\.|http\.|core\.(fsmonitor|sshcommand|gitproxy)|remote\..*\.promisor|extensions\.partialclone)'


class Stop(Exception):
    pass


def protected_store(value):
    path = Path(value)
    if (not value.startswith('/') or value == '/' or str(path) != value or
            '..' in path.parts or any(ord(c) < 32 for c in value)):
        raise Stop('INVALID_STORE_PATH')
    for parent in (path, *path.parents):
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise Stop('UNTRUSTED_STORE_DIRECTORY')
    if path.lstat().st_mode & 0o077:
        raise Stop('STORE_NOT_PRIVATE')
    return path


def run_git(store, args, *, seconds=6, accepted=(0,)):
    # Only the constant operations assembled below reach this function. The CLI
    # cannot change the remote, pin, refspec, Git options, executable or environment.
    child = subprocess.Popen(
        ['/usr/bin/git', *OPTIONS, '--git-dir=' + str(store), *args],
        env=ENV, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, start_new_session=True,
    )
    selector = selectors.DefaultSelector()
    out = bytearray()
    end = time.monotonic() + seconds
    try:
        selector.register(child.stdout, selectors.EVENT_READ)
        while selector.get_map():
            remaining = end - time.monotonic()
            if remaining <= 0:
                raise Stop('GIT_TIMEOUT_PRESERVE_STATE')
            for key, _ in selector.select(min(.1, remaining)):
                chunk = os.read(key.fd, min(4096, 65537 - len(out)))
                if not chunk:
                    selector.unregister(key.fileobj)
                else:
                    out.extend(chunk)
                    if len(out) > 65536:
                        raise Stop('GIT_OUTPUT_BOUND_PRESERVE_STATE')
        code = child.wait(timeout=max(.001, end - time.monotonic()))
        if code not in accepted:
            raise Stop('GIT_FAILED_PRESERVE_STATE')
        return code, bytes(out)
    finally:
        selector.close()
        if child.poll() is None:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait(timeout=2)
        child.stdout.close()


def metadata_file(store, name):
    path = store / name
    try:
        before = path.lstat()
    except FileNotFoundError:
        return None
    if (not stat.S_ISREG(before.st_mode) or before.st_uid != 0 or
            before.st_mode & 0o022 or before.st_size > 65536):
        raise Stop('UNSAFE_GIT_METADATA')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        opened = os.fstat(fd)
        if (before.st_dev, before.st_ino, before.st_size) != (
                opened.st_dev, opened.st_ino, opened.st_size):
            raise Stop('GIT_METADATA_CHANGED')
        data = os.read(fd, 65537)
        if len(data) != before.st_size:
            raise Stop('GIT_METADATA_CHANGED')
        return data
    finally:
        os.close(fd)


def snapshot(store, run):
    _, refs = run(store, ('for-each-ref', '--format=%(refname) %(objectname)'))
    return refs, metadata_file(store, 'HEAD'), metadata_file(store, 'FETCH_HEAD')


def present(store, pin, run):
    code, out = run(store, ('cat-file', '-t', pin), accepted=(0, 128))
    if code == 128:
        return False
    if out != b'commit\n':
        raise Stop('WRONG_OBJECT_TYPE')
    return True


def prepare(value, *, apply=False, run=run_git):
    if os.geteuid() != 0:
        raise Stop('ROOT_REQUIRED')
    store = protected_store(value)
    if run(store, ('rev-parse', '--is-bare-repository'))[1] != b'true\n':
        raise Stop('BARE_STORE_REQUIRED')
    # Existing shallow/partial histories and auth-bearing configuration need a
    # separate review; never modify or bypass them to make this preparation pass.
    if os.path.lexists(store / 'shallow'):
        raise Stop('SHALLOW_STORE_REQUIRES_REVIEW')
    code, _ = run(store, ('config', '--local', '--no-includes', '--name-only',
                          '--get-regexp', UNSAFE_CONFIG), accepted=(0, 1))
    if code == 0:
        raise Stop('LOCAL_CONFIG_REQUIRES_REVIEW')
    before = snapshot(store, run)
    missing = [pin for pin in PINS if not present(store, pin, run)]
    if missing and not apply:
        print('SOURCE_PLAN: public pinned objects needed; no changes made')
        return
    if missing:
        try:
            run(store, FETCH, seconds=120)
        finally:
            if snapshot(store, run) != before:
                raise Stop('REF_OR_HEAD_CHANGED_PRESERVE_STATE')
        if not all(present(store, pin, run) for pin in PINS):
            raise Stop('PIN_VERIFICATION_FAILED_PRESERVE_STATE')
    for older, newer in ((PINS[2], PINS[1]), (PINS[1], PINS[0]),
                         (PINS[0], PINS[3]), (PINS[3], SOURCE)):
        run(store, ('merge-base', '--is-ancestor', older, newer))
    if snapshot(store, run) != before:
        raise Stop('REF_OR_HEAD_CHANGED_PRESERVE_STATE')
    print('SOURCE_OBJECTS: VERIFIED')
    print('REFS_HEAD_FETCH_HEAD: UNCHANGED')
    print('RUNNER_CREDENTIALS_SERVICES: UNTOUCHED')
    print('OVERALL: NO-GO — source preparation only; no runtime authorization')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', required=True)
    parser.add_argument('--apply', action='store_true', help='add public Git objects only')
    args = parser.parse_args()
    try:
        prepare(args.store, apply=args.apply)
    except Stop as exc:
        print('STOP: ' + str(exc))  # fixed codes only, never Git stderr or private paths
        return 1
    except Exception:
        print('STOP: UNVERIFIED_STATE; preserve files; no automatic retry')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
