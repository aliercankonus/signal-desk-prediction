#!/usr/bin/env python3
"""Persistent, fail-closed development task queue; run workers outside a live chat."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import uuid

from checkpoint import SECRET_RE
from task_session import SESSION_ID, make_task_prompt, project_checkpoints, repo_root

HOME = Path('/opt/data/autonomous-development')
_SHUTDOWN = threading.Event()


class ShutdownRequested(Exception):
    """Leave an in-flight task running for manual review; never replay it."""


def _terminate_group(process: subprocess.Popen) -> None:
    """Stop only this worker's process group, including its tool children."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()


def run_interruptible(argv: list[str], *, cwd: Path | str | None = None,
                      timeout: int = 60, check: bool = False,
                      shutdown: threading.Event | None = None) -> subprocess.CompletedProcess:
    """Bounded child process with group shutdown on SIGTERM; no shell or retries."""
    stop = shutdown if shutdown is not None else _SHUTDOWN
    if stop.is_set():
        raise ShutdownRequested('shutdown before child launch')
    process = subprocess.Popen(argv, cwd=cwd, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True, start_new_session=True)
    deadline = time.monotonic() + timeout
    try:
        while True:
            if stop.is_set():
                raise ShutdownRequested('child interrupted by shutdown')
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(argv, timeout)
            try:
                stdout, stderr = process.communicate(timeout=min(1, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
    except (ShutdownRequested, KeyboardInterrupt, subprocess.TimeoutExpired):
        _terminate_group(process)
        raise
    result = subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
    if check and process.returncode:
        raise subprocess.CalledProcessError(process.returncode, argv, stdout, stderr)
    return result


def atomic_json(path: Path, data: dict) -> None:
    temporary = path.with_name('.' + path.name + '-' + uuid.uuid4().hex)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, sort_keys=True, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


class TaskStore:
    def __init__(self, root: Path = HOME / 'tasks'):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def load(self, task_id: str) -> dict:
        if not isinstance(task_id, str) or len(task_id) != 32 or not all(c in '0123456789abcdef' for c in task_id):
            raise ValueError('invalid task ID')
        return json.loads((self.root / task_id / 'state.json').read_text(encoding='utf-8'))

    def pending(self) -> list[dict]:
        tasks = [json.loads(p.read_text(encoding='utf-8')) for p in self.root.glob('*/state.json')]
        return sorted((t for t in tasks if t['status'] == 'queued'), key=lambda t: (t['created_ns'], t['id']))

    def submit(self, repo: Path, request: str, *, related: str | None = None,
               checkpoint: Path | None = None) -> dict:
        root = repo_root(Path(repo))
        request = request.strip()
        if not request or len(request) > 2000 or SECRET_RE.search(request) or '\x00' in request:
            raise ValueError('request must be 1–2000 characters and contain no apparent credentials')
        if related:
            parent = self.load(related)
            if parent['repo'] != str(root):
                raise ValueError('related task must use the same repository')
            if parent['status'] == 'blocked':
                raise ValueError('parent task is blocked; resolve it before submitting a continuation')
        selected = None
        if checkpoint:
            selected_path = Path(checkpoint).expanduser().resolve(strict=True)
            if not selected_path.is_file() or not selected_path.is_relative_to(project_checkpoints(root).resolve()):
                raise ValueError('checkpoint must be an existing handoff for this repository')
            selected = str(selected_path)
        task_id = uuid.uuid4().hex
        folder = self.root / task_id
        folder.mkdir(mode=0o700)
        brief = folder / 'brief.md'
        fd = os.open(brief, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write('# Development task\n\n' + request + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        task = {'id': task_id, 'repo': str(root), 'brief': str(brief), 'related': related,
                'checkpoint': selected, 'status': 'queued', 'created_ns': time.time_ns()}
        atomic_json(folder / 'state.json', task)
        return task

    def save(self, task: dict) -> None:
        atomic_json(self.root / task['id'] / 'state.json', task)

    def running(self) -> list[dict]:
        return [t for t in self.all_tasks() if t.get('status') == 'running']

    def quota_pauses(self) -> list[dict]:
        return [t for t in self.all_tasks() if t.get('status') == 'blocked'
                and t.get('failure_code') == 'quota' and not t.get('quota_ack_ns')]

    def pauses(self) -> list[dict]:
        return [t for t in self.all_tasks() if t.get('status') == 'blocked'
                and t.get('failure_code') != 'quota' and not t.get('block_ack_ns')]

    def acknowledge_block(self, task_id: str) -> dict:
        task = self.load(task_id)
        if task.get('status') != 'blocked' or task.get('failure_code') == 'quota':
            raise ValueError('task has no non-quota block to acknowledge')
        task['block_ack_ns'] = time.time_ns()
        self.save(task)
        return task

    def acknowledge_quota(self, task_id: str) -> dict:
        task = self.load(task_id)
        if task.get('status') != 'blocked' or task.get('failure_code') != 'quota':
            raise ValueError('task has no quota pause to acknowledge')
        task['quota_ack_ns'] = time.time_ns()
        self.save(task)
        return task

    def all_tasks(self) -> list[dict]:
        return sorted((json.loads(p.read_text(encoding='utf-8'))
                       for p in self.root.glob('*/state.json')),
                      key=lambda t: (t['created_ns'], t['id']))


def monitor_snapshot(root: Path) -> dict[str, int]:
    """Read-only queue counts for the credential-free observer; no task contents in logs."""
    counts = dict.fromkeys(('queued', 'running', 'blocked', 'completed'), 0)
    for path in Path(root).glob('*/state.json'):
        state = json.loads(path.read_text(encoding='utf-8'))['status']
        if state not in counts:
            raise ValueError('unknown queue state')
        counts[state] += 1
    return counts


def git_fingerprint(repo: Path) -> str:
    """Observe HEAD, tracked diff, and untracked files without changing Git state."""
    root = Path(repo)
    digest = hashlib.sha256()
    for args in (('rev-parse', 'HEAD'), ('diff', '--no-ext-diff', '--binary', 'HEAD'),
                 ('status', '--porcelain=v1', '-z', '--untracked-files=all')):
        result = subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True)
        digest.update(result.stdout)
        digest.update(b'\0')
    untracked = subprocess.run(['git', '-C', str(root), 'ls-files', '--others', '--exclude-standard', '-z'],
                               check=True, capture_output=True).stdout
    for raw in sorted(p for p in untracked.split(b'\0') if p):
        file = root / os.fsdecode(raw)
        if file.is_symlink():
            digest.update(raw + b'\0' + os.fsencode(os.readlink(file)))
        elif file.is_file():
            digest.update(raw + b'\0')
            stat = file.stat()
            digest.update(f'{stat.st_size}:{stat.st_mtime_ns}'.encode())
            if stat.st_size <= 2_000_000:
                digest.update(file.read_bytes())
    return digest.hexdigest()


def execute_task(task: dict, resume_id: str | None, *, hermes: str = 'hermes',
                 timeout: int = 3900, shutdown: threading.Event | None = None) -> dict:
    """Single bounded model turn. Never invoke this from the active Hermes chat."""
    root = Path(task['repo'])
    folder = Path(task['brief']).parent
    prompt = make_task_prompt(root, task['id'], Path(task['brief']),
                              Path(task['checkpoint']) if task['checkpoint'] else None,
                              supervised=True)
    prompt_file = folder / 'prompt.txt'
    fd = os.open(prompt_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        stream.write(prompt + '\n')
    argv = [hermes, 'chat', '--in', str(root), '--oneshot', '--query-file', str(prompt_file),
            '--format', 'stream-json', '--source', 'autonomous-development',
            '--max-turns', '80', '--run-budget', '3600']
    if resume_id:
        if not SESSION_ID.fullmatch(resume_id):
            raise ValueError('invalid related session ID')
        argv.extend(['--resume', resume_id, '--no-restore-cwd'])
    try:
        result = run_interruptible(argv, cwd=root, timeout=timeout, shutdown=shutdown)
    except subprocess.TimeoutExpired:
        return {'exit_code': 124, 'session_id': '', 'text': '', 'error': 'time budget exceeded'}
    terminal = None
    for line in result.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get('type') == 'result':
            terminal = event
    if terminal is None:
        error_text = result.stderr.lower()
        code = 'quota' if any(x in error_text for x in ('429', 'quota', 'rate limit', 'usage limit')) else 'agent'
        return {'exit_code': result.returncode or 1, 'session_id': '', 'text': '', 'error': code}
    error_text = (result.stderr + str(terminal.get('error', ''))).lower()
    code = 'quota' if any(x in error_text for x in ('429', 'quota', 'rate limit', 'usage limit')) else 'agent'
    return {'exit_code': result.returncode or terminal.get('exit_code', 1),
            'session_id': terminal.get('session_id', ''), 'text': terminal.get('text', ''),
            'error': code if result.returncode or terminal.get('error') else ''}


def verify_task(task: dict) -> dict:
    """Check Git whitespace and execute actual detected test-phase commands."""
    root = task['repo']
    diff = subprocess.run(['git', '-C', root, 'diff', '--check'], capture_output=True, text=True)
    if diff.returncode:
        return {'ok': False, 'summary': 'git diff --check failed'}
    detected = run_interruptible(['hermes', 'verify', root, '--detect-only', '--json'], timeout=60)
    if detected.returncode:
        return {'ok': False, 'summary': 'no detectable test recipe'}
    try:
        recipe = json.loads(detected.stdout)['recipe']
        commands = recipe.get('test', [])
    except (ValueError, KeyError, TypeError):
        return {'ok': False, 'summary': 'invalid detected test recipe'}
    if not commands:
        return {'ok': False, 'summary': 'no test commands; manual verification required'}
    verified = run_interruptible(['hermes', 'verify', root, '--phase', 'test', '--skip-start',
                                  '--timeout', '600', '--json'], timeout=1800)
    try:
        payload = json.loads(verified.stdout)
        phases = payload['phases']
        ok = verified.returncode == 0 and payload['ok'] and phases and all(
            p['phase'] == 'test' and p['ok'] for p in phases)
        summary = '; '.join(f"{p['command'][:150]} (exit {p['exitCode']})" for p in phases)
        after_diff = subprocess.run(['git', '-C', root, 'diff', '--check'], capture_output=True, text=True)
        if after_diff.returncode:
            return {'ok': False, 'summary': 'git diff --check failed after tests'}
        return {'ok': bool(ok), 'summary': ('PASS: ' if ok else 'FAIL: ') + summary[:1000]}
    except (ValueError, KeyError, TypeError):
        return {'ok': False, 'summary': 'test runner did not return valid phase evidence'}


def write_checkpoint(task: dict, tests: str, decisions: str, remaining: str,
                     session_id: str, *, output_root: Path = Path('/opt/data/development-checkpoints')) -> Path:
    command = [sys.executable, str(HOME / 'checkpoint.py'), '--repo', task['repo'],
               '--task', task['id'], '--tests', tests, '--decisions', decisions,
               '--remaining', remaining, '--session', session_id, '--output-root', str(output_root)]
    result = run_interruptible(command, check=True, timeout=60)
    path = Path(result.stdout.strip())
    if not path.is_file() or f'Session: `{session_id}`' not in path.read_text(encoding='utf-8'):
        raise RuntimeError('checkpoint readback failed')
    return path


def run_queue(store: TaskStore, executor=execute_task, verifier=verify_task,
              checkpoint_writer=write_checkpoint, *, max_tasks: int = 20,
              allowed_repo: Path | None = None) -> dict:
    """One bounded queue drain. Failure blocks current task and halts; never retries."""
    completed = 0
    if store.running():
        return {'completed': 0, 'stopped': 'stale running task requires manual review'}
    if store.quota_pauses():
        return {'completed': 0, 'stopped': 'quota pause requires explicit acknowledgment after reset'}
    if store.pauses():
        return {'completed': 0, 'stopped': 'task pause requires manual review and acknowledgment'}
    while completed < max_tasks:
        pending = store.pending()
        if not pending:
            return {'completed': completed, 'stopped': 'empty'}
        task = pending[0]
        if allowed_repo is not None:
            try:
                if Path(task['repo']).resolve(strict=True) != Path(allowed_repo).resolve(strict=True):
                    return {'completed': completed, 'stopped': 'repository outside approved workspace'}
            except (OSError, ValueError):
                return {'completed': completed, 'stopped': 'repository unavailable for approval check'}
        resume_id = None
        if task['related']:
            parent = store.load(task['related'])
            if parent['status'] != 'completed' or not parent.get('session_id'):
                return {'completed': completed, 'stopped': 'related parent not completed'}
            resume_id = parent['session_id']
        task['status'] = 'running'
        task['started_ns'] = time.time_ns()
        store.save(task)  # crashes leave running, never silently replay a possibly charged turn
        failure_code = 'task'
        try:
            before = git_fingerprint(Path(task['repo']))
            response = executor(task, resume_id)
            session_id = response.get('session_id', '')
            if response.get('exit_code') != 0 or not SESSION_ID.fullmatch(session_id):
                error = str(response.get('error', '')).lower()
                failure_code = 'quota' if any(x in error for x in ('429', 'quota', 'rate limit', 'usage limit')) else 'agent'
                raise ValueError('agent failed or did not return a valid session ID')
            if resume_id and session_id != resume_id:
                raise ValueError('related subtask did not resume the parent session')
            text = response.get('text', '')
            if not isinstance(text, str) or len(text) > 2000 or SECRET_RE.search(text):
                raise ValueError('agent completion is oversized or contains an apparent credential')
            report = json.loads(text)
            if (not isinstance(report, dict) or report.get('status') != 'complete'
                    or report.get('remaining') != 'none' or not isinstance(report.get('decisions'), str)
                    or not report['decisions'].strip() or len(report['decisions']) > 1000):
                raise ValueError('agent did not attest task completion in the required format')
            if before == git_fingerprint(Path(task['repo'])):
                raise ValueError('no observable Git changes; manual review required')
            evidence = verifier(task)
            if not evidence['ok'] or not evidence.get('summary'):
                failure_code = 'verification'
                raise ValueError('test verification failed or no test evidence')
            checkpoint_path = checkpoint_writer(task, evidence['summary'], report['decisions'],
                                                'none', session_id)
            if not Path(checkpoint_path).is_file():
                raise ValueError('checkpoint missing after write')
            task.update(status='completed', session_id=session_id,
                        checkpoint_written=str(checkpoint_path), tests=evidence['summary'],
                        finished_ns=time.time_ns())
            store.save(task)
            completed += 1
        except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError) as exc:
            # Never persist raw exceptions: provider errors and commands may contain secrets.
            task.update(status='blocked', failure_type=type(exc).__name__, failure_code=failure_code,
                        finished_ns=time.time_ns())
            store.save(task)
            return {'completed': completed, 'stopped': f'blocked {task["id"]} ({type(exc).__name__})'}
    return {'completed': completed, 'stopped': 'task limit reached'}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', type=Path, default=HOME / 'tasks', help='Persistent task store')
    sub = parser.add_subparsers(dest='action', required=True)
    submit = sub.add_parser('submit', help='Queue one natural-language task; never starts a model')
    submit.add_argument('--repo', type=Path, required=True)
    text = submit.add_mutually_exclusive_group(required=True)
    text.add_argument('--text')
    text.add_argument('--text-file', help='Path to request text; - reads stdin')
    submit.add_argument('--related', help='Task ID to continue in the SAME session')
    submit.add_argument('--checkpoint', type=Path, help='One relevant handoff from this repository')
    sub.add_parser('status', help='Read-only queue status')
    sub.add_parser('monitor', help='Credential-free read-only queue counts; never launches a worker')
    ack = sub.add_parser('ack-quota', help='After verified quota reset, acknowledge a blocked 429; never retries it')
    ack.add_argument('--task', required=True, help='Blocked task ID')
    ack_block = sub.add_parser('ack-block', help='After manual review, release a non-quota pause; never retries it')
    ack_block.add_argument('--task', required=True, help='Blocked task ID')
    run = sub.add_parser('run', help='External supervisor: run separately from this conversation')
    run.add_argument('--watch', action='store_true', help='Keep watching for submitted tasks')
    run.add_argument('--max-tasks', type=int, default=20, help='Max consecutive tasks per drain (1-50)')
    run.add_argument('--allowed-repo', type=Path, help='Exact mounted repository; refuse other queued tasks')
    args = parser.parse_args(argv)
    if args.action == 'monitor':
        while True:
            try:
                print(json.dumps(monitor_snapshot(args.store)), flush=True)
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                print('queue monitoring unavailable', file=sys.stderr, flush=True)
            time.sleep(30)
    store = TaskStore(args.store)
    if args.action == 'submit':
        if args.text_file == '-':
            request = sys.stdin.read(2002)
        elif args.text_file:
            with open(args.text_file, encoding='utf-8') as stream:
                request = stream.read(2002)
        else:
            request = args.text
        try:
            task = store.submit(args.repo, request, related=args.related, checkpoint=args.checkpoint)
        except (OSError, ValueError, subprocess.CalledProcessError) as exc:
            parser.error(str(exc) if not SECRET_RE.search(str(exc)) else 'request rejected')
        print(json.dumps(task, sort_keys=True))
        return 0
    if args.action == 'status':
        print(json.dumps([{'id': t['id'], 'repo': t['repo'], 'status': t['status'],
                           'related': t['related'], 'session_id': t.get('session_id'),
                           'checkpoint_written': t.get('checkpoint_written'),
                           'failure_type': t.get('failure_type'),
                           'failure_code': t.get('failure_code'),
                           'quota_acknowledged': bool(t.get('quota_ack_ns')),
                           'block_acknowledged': bool(t.get('block_ack_ns'))}
                          for t in store.all_tasks()], indent=2))
        return 0
    if args.action == 'ack-quota':
        try:
            task = store.acknowledge_quota(args.task)
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
        print(json.dumps({'id': task['id'], 'status': task['status'], 'quota_acknowledged': True}))
        return 0
    if args.action == 'ack-block':
        try:
            task = store.acknowledge_block(args.task)
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
        print(json.dumps({'id': task['id'], 'status': task['status'], 'block_acknowledged': True}))
        return 0
    if not 1 <= args.max_tasks <= 50:
        parser.error('--max-tasks must be between 1 and 50')
    _SHUTDOWN.clear()
    signal.signal(signal.SIGTERM, lambda _signum, _frame: _SHUTDOWN.set())
    signal.signal(signal.SIGINT, lambda _signum, _frame: _SHUTDOWN.set())
    lock_file = store.root / '.runner.lock'
    with open(lock_file, 'a+', encoding='utf-8') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error('another supervisor holds this task store')
        while not _SHUTDOWN.is_set():
            try:
                outcome = run_queue(store, max_tasks=args.max_tasks, allowed_repo=args.allowed_repo)
            except ShutdownRequested:
                print('shutdown: in-flight task retained as running for manual review', flush=True)
                return 0
            print(json.dumps(outcome), flush=True)
            if not args.watch:
                return 0 if outcome['stopped'] in ('empty', 'task limit reached') else 1
            if outcome['stopped'] != 'task limit reached':
                # Failures remain durably paused; keep the sidecar alive without
                # restarting (and without another provider request) until reviewed.
                _SHUTDOWN.wait(5)
        return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('supervisor interrupted; inspect any running task before restarting', file=sys.stderr)
        sys.exit(130)
