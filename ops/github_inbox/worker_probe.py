#!/usr/bin/env python3
"""Read-only authenticated checks from the actual isolated worker namespace."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

REPO = 'aliercankonus/signal-desk-prediction'


def probe(adapter, git, repo, issue):
    if repo != REPO or issue != 43:
        raise ValueError('probe outside frozen task')
    user = adapter.request('GET', '/user')
    task = adapter.request('GET', f'/repos/{repo}/issues/{issue}')
    for number in (41, 45):
        item = adapter.request('GET', f'/repos/{repo}/issues/{number}')
        if item.get('number') != number:
            raise ValueError('inbox issue GET mismatch')
    target = adapter.request('GET', f'/repos/{repo}/git/ref/heads/main')
    pin = 'e84021a786004456a12de9e25eae50d191da6cf1'
    checks = adapter.request('GET', f'/repos/{repo}/commits/{pin}/check-runs?per_page=100')
    candidates = adapter.request('GET', f'/repos/{repo}/pulls?state=all&head=aliercankonus:issue43-one-shot-review-note&per_page=2')
    head = git('ls-remote', 'origin', 'HEAD')
    branch = git('ls-remote', 'origin', 'refs/heads/issue43-one-shot-review-note')
    if not isinstance(user.get('login'), str) or not user['login'] or not head:
        raise ValueError('worker GitHub credentials not usable')
    if (target.get('ref') != 'refs/heads/main' or
            target.get('object', {}).get('type') != 'commit' or
            not isinstance(checks.get('check_runs'), list) or
            not isinstance(checks.get('total_count'), int) or
            checks['total_count'] > len(checks['check_runs']) or
            candidates != [] or branch):
        raise ValueError('task branch/PR/Checks read-only gate failed')
    if task.get('number') != issue or task.get('state') != 'open':
        raise ValueError('frozen task closed or unavailable')
    return {'authenticated': True, 'task_open': True, 'git_read': True}


def main():
    runner = Path('/workspace/runner')
    sys.path[:0] = [str(runner / 'src'), str(runner / 'autonomous-development')]
    from signal_desk.task_bridge.bridge import load_authorization
    from signal_desk.task_bridge.adapters import GitHubREST
    policy = load_authorization('/private/auth/authorization.json')
    if policy.repo != REPO or policy.issue != 43:
        raise ValueError('unexpected worker policy')
    adapter = GitHubREST(policy)
    def git(*parts):
        completed = subprocess.run(['git', '-C', str(runner), *parts],
            capture_output=True, check=True, timeout=15)
        if len(completed.stdout) > 4096:
            raise ValueError('git result oversized')
        return completed.stdout.decode('ascii')
    result = probe(adapter, git, REPO, 43)
    task = adapter.issue(REPO, 43)
    if hashlib.sha256(task['body'].encode('utf-8')).hexdigest() != policy.body_digest:
        raise ValueError('frozen task body changed')
    # Do not print usernames, remote body, Git output, credentials or paths.
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
