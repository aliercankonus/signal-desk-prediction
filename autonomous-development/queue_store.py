"""Selected, inert queue persistence from reviewed Worker snapshot 92ee0f4e.

No task submission CLI, execute_task, Hermes child, watcher, or supervisor.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import uuid
import weakref


ID = re.compile(r'[0-9a-f]{32}\Z')
MAX_STATE = 16384
LEGACY_ROOT = Path('/opt/data/autonomous-development/tasks')


def _trusted_ancestors(path: Path) -> None:
    """The queue's pathname must not pass through a replaceable ancestor."""
    current = path
    while True:
        info = current.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0, os.geteuid()) or
                info.st_mode & 0o022):
            raise PermissionError('queue ancestor is untrusted or replaceable')
        if current.parent == current:
            return
        current = current.parent


def _private_directory(path: Path) -> None:
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise PermissionError('queue directory must be owned and private, not a symlink')


def atomic_json(path: Path, data: dict, *, directory_fd: int) -> None:
    """Worker snapshot's fsynced 0600 temporary + atomic replacement, fd-anchored."""
    info = os.fstat(directory_fd)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise PermissionError('queue task directory must be private')
    name = path.name
    if name != 'state.json':
        raise ValueError('unexpected queue state name')
    try:
        named = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        if not stat.S_ISREG(named.st_mode) or named.st_mode & 0o077:
            raise PermissionError('queue state must be a private regular file')
    temporary = '.' + name + '-' + uuid.uuid4().hex
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 0o600, dir_fd=directory_fd)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, sort_keys=True, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        os.fsync(directory_fd)
    finally:
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except FileNotFoundError:
            pass


class TaskStore:
    """Explicitly located bridge-only queue; no legacy Worker execution API."""

    def __init__(self, root: Path, *, create: bool = True):
        self.root = Path(root)
        if not self.root.is_absolute() or self.root.is_symlink() or self.root != self.root.resolve():
            raise ValueError('absolute non-symlink queue root required')
        if self.root == LEGACY_ROOT:
            raise ValueError('legacy Worker queue root cannot be shared')
        parent = self.root.parent
        _trusted_ancestors(parent)
        if self.root.exists():
            _private_directory(self.root)
        else:
            if not create:
                raise FileNotFoundError('queue root absent for read-only inspection')
            self.root.mkdir(mode=0o700)
            _private_directory(self.root)
            parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
        self._root_fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        self._closer = weakref.finalize(self, os.close, self._root_fd)
        root_info = os.fstat(self._root_fd)
        self._identity = (root_info.st_dev, root_info.st_ino)

    def _check(self) -> None:
        parent = self.root.parent
        _trusted_ancestors(parent)
        if self.root.resolve(strict=True) != self.root:
            raise PermissionError('queue path changed')
        _private_directory(self.root)
        root_info = self.root.lstat()
        if (root_info.st_dev, root_info.st_ino) != self._identity:
            raise PermissionError('queue directory identity changed')

    def create_entry_directory(self, task_id: str) -> Path:
        """Durably publish a private task directory before writing any state."""
        if not isinstance(task_id, str) or not ID.fullmatch(task_id):
            raise ValueError('invalid queue ID')
        self._check()
        os.mkdir(task_id, mode=0o700, dir_fd=self._root_fd)
        directory_fd = os.open(task_id, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                               dir_fd=self._root_fd)
        try:
            info = os.fstat(directory_fd)
            if info.st_uid != os.geteuid() or info.st_mode & 0o077:
                raise PermissionError('queue task directory must be private')
            os.fsync(self._root_fd)
        finally:
            os.close(directory_fd)
        self._check()
        return self.root / task_id

    @contextmanager
    def _task_fd(self, task_id: str):
        if not isinstance(task_id, str) or not ID.fullmatch(task_id):
            raise ValueError('invalid queue ID')
        self._check()
        fd = os.open(task_id, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                     dir_fd=self._root_fd)
        try:
            info = os.fstat(fd)
            if info.st_uid != os.geteuid() or info.st_mode & 0o077:
                raise PermissionError('queue task directory must be private')
            self._check()
            yield fd
        finally:
            os.close(fd)

    def load(self, task_id: str) -> dict:
        with self._task_fd(task_id) as directory_fd:
            fd = os.open('state.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                         dir_fd=directory_fd)
            try:
                info = os.fstat(fd)
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or
                        info.st_mode & 0o077 or info.st_size > MAX_STATE):
                    raise PermissionError('queue state must be bounded private regular file')
                data = os.read(fd, MAX_STATE + 1)
                after = os.fstat(fd)
                named = os.stat('state.json', dir_fd=directory_fd, follow_symlinks=False)
                if (len(data) != info.st_size or
                        (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns) !=
                        (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) or
                        (named.st_dev, named.st_ino) != (info.st_dev, info.st_ino)):
                    raise ValueError('queue state changed while reading')
            finally:
                os.close(fd)
        result = json.loads(data.decode('utf-8'))
        if not isinstance(result, dict) or result.get('id') != task_id or result.get('kind') != 'bridge':
            raise ValueError('queue entry identity invalid')
        return result

    def save(self, task: dict) -> None:
        with self._task_fd(task['id']) as directory_fd:
            atomic_json(Path('state.json'), task, directory_fd=directory_fd)

    def all_tasks(self) -> list[dict]:
        self._check()
        entries = []
        for name in os.listdir(self._root_fd):
            if name.startswith('.'):
                continue
            if not ID.fullmatch(name):
                raise ValueError('unexpected queue entry')
            item = self.load(name)
            if (item.get('status') not in ('queued', 'running', 'blocked', 'review-ready') or
                    type(item.get('created_ns')) is not int):
                raise ValueError('queue state incomplete or invalid')
            entries.append(item)
        return sorted(entries, key=lambda t: (t['created_ns'], t['id']))

    def acknowledge_block(self, task_id: str) -> dict:
        """Reviewed Worker acknowledgment, never a retry authorization."""
        import time
        task = self.load(task_id)
        if task.get('status') != 'blocked' or task.get('failure_code') == 'quota':
            raise ValueError('task has no non-quota block to acknowledge')
        task['block_ack_ns'] = time.time_ns()
        self.save(task)
        return task

    @contextmanager
    def lock(self):
        """Local lock on a verified private regular inode; not a distributed claim."""
        self._check()
        fd = os.open('.runner.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600, dir_fd=self._root_fd)
        try:
            info = os.fstat(fd)
            named = os.stat('.runner.lock', dir_fd=self._root_fd, follow_symlinks=False)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or
                    info.st_mode & 0o077 or info.st_nlink != 1 or
                    (info.st_dev, info.st_ino) != (named.st_dev, named.st_ino)):
                raise PermissionError('queue lock must be a private regular inode')
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
            else:
                self._check()
                named = os.stat('.runner.lock', dir_fd=self._root_fd, follow_symlinks=False)
                if (named.st_dev, named.st_ino) != (info.st_dev, info.st_ino):
                    raise PermissionError('queue lock replaced')
                yield True
        finally:
            os.close(fd)


def monitor_snapshot(root: Path) -> dict[str, int]:
    """Read-only counts; review-ready never aliases completed or CI success."""
    counts: dict[str, int] = dict.fromkeys(('queued', 'running', 'blocked', 'review-ready', 'completed'), 0)
    root = Path(root)
    if root.is_symlink():
        raise PermissionError('queue root symlink denied')
    if not root.exists():
        return counts
    for item in TaskStore(root, create=False).all_tasks():
        status = item['status']
        if status not in counts:
            raise ValueError('unknown queue state')
        counts[status] += 1
    return counts
