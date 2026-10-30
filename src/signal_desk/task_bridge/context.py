"""Private, bounded execution context; separate from issue/task authorization."""
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import shlex
import signal
import stat
import subprocess
import time
from types import SimpleNamespace


@dataclass(frozen=True)
class ExecutionContext:
    test_python: str
    requirements_sha256: str
    runner_commit: str
    python_version: str
    pytest_version: str

    def __post_init__(self):
        path = self.test_python
        if (not isinstance(path, str) or not 1 <= len(path) <= 512 or
            not Path(path).is_absolute() or any(ord(ch) < 32 for ch in path) or
            '..' in Path(path).parts or not isinstance(self.requirements_sha256, str) or
            not re.fullmatch(r'[0-9a-f]{64}', self.requirements_sha256) or
            not isinstance(self.runner_commit, str) or
            not re.fullmatch(r'[0-9a-f]{40}', self.runner_commit) or
            not isinstance(self.python_version, str) or
            not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', self.python_version) or
            not isinstance(self.pytest_version, str) or
            not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', self.pytest_version)):
            raise ValueError('invalid private execution context')


def _bounded_file(path, limit, private=False):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise ValueError('execution context/file exceeds bound or is not regular')
        if private and (before.st_uid != os.geteuid() or before.st_mode & 0o077):
            raise PermissionError('execution context must be owned and private')
        data = os.read(fd, limit + 1)
        after = os.fstat(fd)
        named = Path(path).lstat()
        identity = lambda s: (s.st_dev, s.st_ino, s.st_mode, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        if (len(data) != before.st_size or len(data) > limit or identity(before) != identity(after) or
            (named.st_dev, named.st_ino) != (before.st_dev, before.st_ino)):
            raise ValueError('execution context/file changed or exceeds bound')
        return data
    finally:
        os.close(fd)


def load_execution_context(path, source, state):
    path, source, state = Path(path), Path(source).resolve(), Path(state).resolve()
    actual = path.resolve()
    if (actual == source or source in actual.parents or
        actual == state or state in actual.parents):
        raise ValueError('execution context must be separate from checkout and state')
    parent = path.parent.stat()
    if parent.st_uid != os.geteuid() or parent.st_mode & 0o077:
        raise PermissionError('execution context parent must be private')
    data = _bounded_file(path, 2048, private=True)
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate execution context field')
            result[key] = value
        return result
    record = json.loads(data.decode('utf-8'), object_pairs_hook=unique)
    if not isinstance(record, dict) or set(record) != set(ExecutionContext.__dataclass_fields__):
        raise ValueError('execution context fields mismatch')
    context = ExecutionContext(**record)
    named_interpreter = Path(context.test_python).absolute()
    resolved_interpreter = named_interpreter.resolve()
    if any(path == source or source in path.parents or path == state or state in path.parents
           for path in (named_interpreter, resolved_interpreter)):
        raise ValueError('reviewed interpreter must be outside source and worker state')
    return context


def _installed_backend():
    if os.environ.get('TERMINAL_ENV', 'local').strip().lower() != 'local':
        raise ValueError('terminal backend is not local')
    result = _bounded_run(['hermes', 'config', 'get', 'terminal.backend'], timeout=10)
    if result.returncode or result.stdout.strip() != 'local':
        raise ValueError('terminal backend is not confirmed local')
    return 'local'


def _bounded_run(argv, *, timeout=20, capture_output=True, text=True, check=False):
    """Capture at most 2048 bytes per stream, stopping the whole process group."""
    if not (capture_output and text and check is False):
        raise ValueError('unsupported interpreter probe options')
    child = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, start_new_session=True)
    outputs = {'stdout': bytearray(), 'stderr': bytearray()}
    selector = selectors.DefaultSelector()
    deadline = time.monotonic() + timeout
    try:
        for name in outputs:
            selector.register(getattr(child, name), selectors.EVENT_READ, name)
        while True:
            result = os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
            if result is not None and not selector.get_map():
                code = result.si_status if result.si_code == os.CLD_EXITED else -result.si_status
                return SimpleNamespace(returncode=code,
                                       stdout=outputs['stdout'].decode('utf-8', 'replace'),
                                       stderr=outputs['stderr'].decode('utf-8', 'replace'))
            if time.monotonic() >= deadline:
                raise TimeoutError('reviewed interpreter probe timed out')
            for key, _ in selector.select(timeout=0.1):
                chunk = os.read(key.fd, 2049 - len(outputs[key.data]))
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                outputs[key.data].extend(chunk)
                if len(outputs[key.data]) > 2048:
                    raise ValueError('reviewed interpreter output bound exceeded')
    finally:
        selector.close()
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(child.pid, sig)
            except ProcessLookupError:
                pass
            if sig == signal.SIGTERM:
                time.sleep(0.1)
        child.wait(timeout=2)
        for stream in (child.stdout, child.stderr):
            if stream is not None:
                stream.close()


def validate_execution_context(context, source, runner_commit, *, backend_runner=None, runner=None):
    """No issue prose or shell commands influence this pre-dispatch check."""
    if context.runner_commit != runner_commit:
        raise ValueError('reviewed runner commit mismatch')
    backend = (backend_runner or _installed_backend)()
    if backend != 'local':
        raise ValueError('terminal backend not established as local')
    source = Path(source)
    data = _bounded_file(source / 'requirements.txt', 65536)
    actual = hashlib.sha256(data).hexdigest()
    if actual != context.requirements_sha256:
        raise ValueError('reviewed requirements digest mismatch')
    requirements = data.decode('utf-8').splitlines()
    versions = [line.split('==', 1)[1] for line in requirements
                if re.fullmatch(r'pytest==[0-9]+\.[0-9]+\.[0-9]+', line)]
    if len(versions) != 1 or versions[0] != context.pytest_version:
        raise ValueError('requirements lack the reviewed pytest version')
    python = Path(context.test_python)
    venv = python.parent.parent
    if (not python.is_file() or not os.access(python, os.X_OK) or
        not (venv / 'pyvenv.cfg').is_file() or venv.stat().st_uid != os.geteuid() or
        venv.stat().st_mode & 0o077):
        raise ValueError('reviewed interpreter unavailable or not private')
    run = runner or _bounded_run
    script = ('import json,sys,pytest; print(json.dumps({'
              '"version":".".join(map(str,sys.version_info[:3])),'
              '"pytest":pytest.__version__,"prefix":sys.prefix}))')
    observed = run([context.test_python, '-I', '-B', '-c', script],
                   capture_output=True, text=True, timeout=20, check=False)
    if observed.returncode != 0 or len(observed.stdout) > 2048 or len(observed.stderr) > 2048:
        raise ValueError('reviewed interpreter probe failed')
    try:
        info = json.loads(observed.stdout)
    except (ValueError, TypeError):
        raise ValueError('reviewed interpreter probe invalid') from None
    if (info != {'version': context.python_version, 'pytest': context.pytest_version, 'prefix': str(venv)}):
        raise ValueError('reviewed interpreter/version mismatch')
    check = run([context.test_python, '-I', '-B', '-m', 'pip', 'check'],
                capture_output=True, text=True, timeout=20, check=False)
    if (check.returncode != 0 or len(check.stdout) > 2048 or len(check.stderr) > 2048 or
        check.stdout.strip() != 'No broken requirements found.'):
        raise ValueError('reviewed interpreter dependency check failed')
    return context


def write_task_context(state, worktree, context):
    """Atomically create the private handoff; never overwrite a prior attempt."""
    state, worktree = Path(state), Path(worktree)
    if (state.is_symlink() or worktree.is_symlink() or not worktree.is_dir() or
        worktree.parent.absolute() != (state / 'worktrees').absolute()):
        raise ValueError('task worktree outside private state')
    if state.stat().st_mode & 0o077:
        raise PermissionError('private state not private')
    data = (json.dumps({**asdict(context), 'task_worktree': str(worktree)},
                       sort_keys=True, separators=(',', ':')) + '\n').encode('utf-8')
    if len(data) > 2048:
        raise ValueError('task context exceeds bound')
    target = state / 'execution-context.json'
    fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())
    return target


def trusted_context_prompt(context, worktree):
    """Fixed trusted instructions, not a shell template derived from issue prose."""
    python = shlex.quote(context.test_python)
    directory = shlex.quote(str(worktree))
    probe = shlex.quote(
        'import sys,pytest; assert ".".join(map(str,sys.version_info[:3])) == '
        f'{context.python_version!r}; assert pytest.__version__ == {context.pytest_version!r}; '
        'print("APPROVED_CONTEXT_ACCESSIBLE")')
    return (
        'PRIVATE OPERATOR-REVIEWED EXECUTION CONTEXT (not from issue text).\n'
        f'Task worktree: {worktree}\nApproved test interpreter: {context.test_python}\n'
        'Use the Hermes terminal tool to verify this worktree and this interpreter are accessible '
        'before editing. If either is inaccessible, stop before any edit; do not install or substitute '
        'an interpreter. Do not rely on custom environment variables, bare python, or login-shell PATH.\n'
        f'Read-only terminal preflight: cd -- {directory} && test -x {python} && '
        f'{python} -I -B -c {probe}\n'
        'Only after that preflight succeeds, test with the explicit interpreter:\n'
        f'cd -- {directory} && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src '
        f'{python} -B -m pytest -q -p no:cacheprovider\n'
        'Do not expose these private paths in PR or issue text; the bridge publishes only allowlisted status.\n'
    )
