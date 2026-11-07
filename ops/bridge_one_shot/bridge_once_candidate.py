#!/opt/hermes/.venv/bin/python
"""Candidate new-runner caller for #41. DORMANT; do not invoke without approval."""
import os
from pathlib import Path
import subprocess
import sys

RUNNER_COMMIT = 'e84021a786004456a12de9e25eae50d191da6cf1'
ORIGIN = 'https://github.com/aliercankonus/signal-desk-prediction.git'


def git(root: Path, *args: str) -> str:
    return subprocess.run(['git', '-C', str(root), *args], check=True,
                          capture_output=True, text=True, timeout=20).stdout.strip()


def main() -> int:
    if os.environ.get('BRIDGE_ONCE_APPROVED') != 'yes-for-one-frozen-task':
        raise SystemExit('STOP: explicit one-attempt approval marker absent')
    runner = Path(os.environ['RUNNER']).resolve(strict=True)
    if (git(runner, 'rev-parse', '--show-toplevel') != str(runner) or
            git(runner, 'rev-parse', 'HEAD') != RUNNER_COMMIT or
            git(runner, 'remote', 'get-url', 'origin') != ORIGIN or
            git(runner, 'status', '--porcelain=v1', '--untracked-files=all')):
        raise SystemExit('STOP: reviewed runner changed or dirty')
    # Runner-local config must propagate through the shared .git/config to new worktrees.
    for field in ('GIT_AUTHOR_IDENT', 'GIT_COMMITTER_IDENT'):
        if not git(runner, '-c', 'user.useConfigOnly=true', 'var', field):
            raise SystemExit('STOP: Git identity missing')
    queue_root = Path(os.environ['QUEUE_ROOT'])
    auth = Path(os.environ['AUTH_FILE'])
    context = Path(os.environ['CONTEXT_FILE'])
    sys.path[:0] = [str(runner / 'src'), str(runner / 'autonomous-development')]
    from queue_store import TaskStore
    from bridge_queue import BridgeQueue
    store = TaskStore(queue_root, create=False)
    if store.all_tasks():
        raise SystemExit('STOP: queue not empty; read-only reconciliation required')
    queue = BridgeQueue(store)
    entry = queue.enqueue(runner, auth, context, runner_commit=RUNNER_COMMIT)
    print('durable queue mapping:', entry['id'], entry['bridge_run_id'], flush=True)
    result = queue.dispatch_one(BridgeQueue.production_bridge)
    print('one attempt:', result['status'], entry['id'], flush=True)
    return 0 if result['status'] == 'review-ready' else 2


if __name__ == '__main__':
    sys.exit(main())
