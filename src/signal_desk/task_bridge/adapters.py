"""Optional production boundaries; never invoke a real agent in tests."""
import subprocess
import time
import os
import signal
import json
import urllib.request
import urllib.parse
from pathlib import Path
from .bridge import Policy, REPO


class HermesAgent:
    FLAGS = ('--query-file', '--oneshot', '--quiet', '--in', '--max-turns', '--run-budget')

    def __init__(self, source, state, policy: Policy, help_runner=None):
        self.source = source
        self.state = state
        self.policy = policy
        self.help_runner = help_runner or self._installed_help
        self.git_runner = self._git

    def _git(self, args):
        return subprocess.run(['git', '-C', str(self.source), *args], capture_output=True,
                              text=True, timeout=30, check=True).stdout.strip()

    def preflight(self):
        self.check()
        if self.git_runner(['remote', 'get-url', 'origin']) != 'https://github.com/' + self.policy.repo + '.git':
            raise ValueError('source repository not allowed')
        try:
            kind = self.git_runner(['cat-file', '-t', self.policy.base])
        except subprocess.SubprocessError:
            raise ValueError('pinned base commit unavailable') from None
        if kind != 'commit':
            raise ValueError('pinned base commit unavailable')
        # A pre-existing branch, including one in another worktree, is ambiguous.
        try:
            self.git_runner(['show-ref', '--verify', 'refs/heads/' + self.policy.branch])
        except subprocess.CalledProcessError as exc:
            if exc.returncode != 1:
                raise
        else:
            raise ValueError('reviewed branch already exists')
        return True

    def run(self, prompt, worktree):
        self.preflight()
        path = Path(worktree)
        if path.exists() or path.is_symlink():
            raise FileExistsError('worktree already exists')
        parent = Path(self.state) / 'worktrees'
        if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
            raise ValueError('symlinked or invalid worktree parent')
        if path.parent.absolute() != parent.absolute():
            raise ValueError('worktree outside state directory')
        parent.mkdir(parents=True, exist_ok=True)
        self.git_runner(['worktree', 'add', '-b', self.policy.branch, str(path), self.policy.base])
        prompt_path = Path(self.state) / 'prompt'
        fd = os.open(prompt_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w') as output:
            output.write(prompt)
            output.flush()
            os.fsync(output.fileno())
        self.execute(self.command(prompt_path, path))
        head = self.git_runner(['-C', str(path), 'rev-parse', 'HEAD'])
        try:
            self.git_runner(['-C', str(path), 'merge-base', '--is-ancestor', self.policy.base, head])
        except subprocess.SubprocessError:
            raise ValueError('result head is not descended from pinned base') from None
        return {'branch': self.policy.branch, 'head': head}

    @staticmethod
    def _installed_help():
        return subprocess.run(['hermes', 'chat', '--help'], capture_output=True, text=True,
                              timeout=10, check=True).stdout

    def check(self):
        help_text = self.help_runner()
        if any(flag not in help_text for flag in self.FLAGS):
            raise ValueError('installed Hermes lacks required bounded noninteractive flags')
        return True

    def command(self, prompt, worktree):
        self.check()
        return ['hermes', 'chat', '--query-file', str(prompt), '--oneshot', '--quiet',
                '--in', str(worktree), '--max-turns', '12', '--run-budget', '600']
    def execute(self, argv, timeout=630):
        def interrupted(signum, frame):
            raise InterruptedError('agent interrupted')
        previous_handler = signal.signal(signal.SIGTERM, interrupted)
        child = None
        try:
            child = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, start_new_session=True)
            # WNOWAIT observes exit but retains the zombie PID until group
            # cleanup. Reaping first allows this numeric PGID to be recycled.
            deadline = time.monotonic() + timeout
            while True:
                result = os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
                if result is not None:
                    if result.si_code != os.CLD_EXITED or result.si_status != 0:
                        raise RuntimeError('agent failed; inspect worktree manually')
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError('agent wall time exceeded')
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
        finally:
            # A second stop request must not interrupt bounded cleanup.
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            try:
                if child is not None:
                    try:
                        os.killpg(child.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    time.sleep(0.1)
                    try:
                        os.killpg(child.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    # Reap only after both signals; this bounds cleanup even
                    # when the leader exited before its descendants.
                    child.wait(timeout=2)
            finally:
                signal.signal(signal.SIGTERM, previous_handler)


class GitHubREST:
    REPO = REPO
    MAX_RESPONSE = 131072

    @staticmethod
    def _bounded_json(response):
        content = response.read(GitHubREST.MAX_RESPONSE + 1)
        if len(content) > GitHubREST.MAX_RESPONSE:
            raise ValueError('GitHub response exceeds bound')
        return json.loads(content)

    def __init__(self, policy: Policy, request=None):
        self.policy = policy
        self.request = request or self._request

    def _path(self, repo):
        if repo != self.REPO:
            raise ValueError('repository not allowed')
        return '/repos/' + repo

    def _request(self, method, path, payload=None):
        if not ((method == 'GET' and path == '/user') or
                path.startswith('/repos/' + self.REPO + '/')):
            raise ValueError('API path outside allowlist')
        credential = subprocess.run(['git', 'credential', 'fill'], input='protocol=https\nhost=github.com\n\n',
                                    capture_output=True, text=True, timeout=10, check=True).stdout
        password = next((line[9:] for line in credential.splitlines() if line.startswith('password=')), None)
        if not password:
            raise RuntimeError('GitHub credential unavailable')
        body = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request('https://api.github.com' + path, data=body, method=method,
                                     headers={'Authorization': 'Bearer ' + password,
                                              'Accept': 'application/vnd.github+json',
                                              'Content-Type': 'application/json'})
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                raise RuntimeError('GitHub redirect denied')
        with urllib.request.build_opener(NoRedirect).open(req, timeout=15) as response:
            return self._bounded_json(response)

    def issue(self, repo, number):
        if number != self.policy.issue:
            raise ValueError('issue not allowed')
        item = self.request('GET', self._path(repo) + '/issues/' + str(number))
        return {'repo': repo, 'number': item['number'], 'body': item['body'],
                'state': item['state']}

    def draft_pr(self, repo, branch):
        if branch != self.policy.branch:
            raise ValueError('branch not allowed')
        path = self._path(repo)
        query = urllib.parse.urlencode({'state': 'open', 'head': 'aliercankonus:' + branch, 'per_page': 2})
        candidates = self.request('GET', path + '/pulls?' + query)
        if len(candidates) != 1:
            return None
        pr = candidates[0]
        if (pr['head']['ref'] != branch or not pr['draft'] or
            pr['head']['repo']['full_name'] != self.REPO or
            pr['base']['ref'] != 'main' or pr['base']['repo']['full_name'] != self.REPO):
            return None
        head = pr['head']['sha']
        if len(head) != 40 or any(c not in '0123456789abcdef' for c in head):
            return None
        # PR base.sha may be a snapshot. Read the branch ref independently to
        # report the current target tip without changing the task's start pin.
        target = self.request('GET', path + '/git/ref/heads/main')
        if (target.get('ref') != 'refs/heads/main' or
            target.get('object', {}).get('type') != 'commit'):
            return None
        target_tip = target['object'].get('sha')
        if (not isinstance(target_tip, str) or len(target_tip) != 40 or
            any(c not in '0123456789abcdef' for c in target_tip)):
            return None
        # Compare the immutable starting commit to the result head, not to the
        # moving branch tip. Both status and merge-base must support ancestry.
        comparison = self.request('GET', path + '/compare/' + self.policy.base + '...' + head)
        if (comparison.get('status') not in ('ahead', 'identical') or
            comparison.get('merge_base_commit', {}).get('sha') != self.policy.base):
            return None
        checks = self.request('GET', path + '/commits/' + head + '/check-runs?per_page=100')
        workflows = self.request('GET', path + '/actions/runs?' + urllib.parse.urlencode(
            {'head_sha': head, 'per_page': 100}))
        legacy = self.request('GET', path + '/commits/' + head + '/status')
        checked = checks.get('check_runs', [])
        run_list = workflows.get('workflow_runs', [])
        if (checks.get('total_count', len(checked)) > len(checked) or
            workflows.get('total_count', len(run_list)) > len(run_list) or
            legacy.get('sha') != head or
            any(unit.get('head_sha') != head for unit in checked + run_list)):
            return None
        units = checked + run_list
        states = [unit.get('conclusion') if unit.get('status') == 'completed' else 'pending'
                  for unit in units]
        states += [item.get('state') for item in legacy.get('statuses', [])]
        if not states:
            ci_state = 'unknown'
        elif any(state in ('failure', 'timed_out', 'cancelled', 'action_required') for state in states):
            ci_state = 'failure'
        elif all(state == 'success' for state in states):
            ci_state = 'success'
        else:
            ci_state = 'pending'
        return {'url': pr['html_url'], 'draft': True, 'head': head,
                'pinned_start': self.policy.base, 'target_branch': 'main',
                'target_repo': self.REPO, 'target_tip': target_tip,
                'body': pr.get('body') or '', 'ci_head': head, 'ci': ci_state}

    def statuses(self, repo, number, run_id, expected):
        if (number != self.policy.issue or not isinstance(run_id, str) or len(run_id) != 32 or
            not isinstance(expected, dict) or len(expected) > 4):
            raise ValueError('status lookup outside allowlist')
        path = self._path(repo)
        actor = self.request('GET', '/user').get('login')
        if not isinstance(actor, str) or not actor:
            raise ValueError('authenticated comment author unavailable')
        observed = []
        for page in range(1, 6):
            rows = self.request('GET', path + '/issues/' + str(number) + '/comments?' +
                                urllib.parse.urlencode({'per_page': 100, 'page': page}))
            if not isinstance(rows, list) or len(rows) > 100:
                raise ValueError('unbounded issue comments')
            for row in rows:
                body = row.get('body')
                if (not isinstance(body, str) or len(body) > 2048 or
                    row.get('user', {}).get('login') != actor):
                    continue
                try:
                    item = json.loads(body)
                except (ValueError, TypeError):
                    continue
                if (isinstance(item, dict) and item.get('run_id') == run_id and
                    item.get('status') in expected and
                    body == expected[item['status']] and
                    type(row.get('id')) is int and row['id'] > 0):
                    observed.append({'id': row['id'], 'status': item['status']})
                    if len(observed) > 4:
                        raise ValueError('too many matching publications')
            if len(rows) < 100:
                return observed
        raise ValueError('issue comment history exceeds inspection bound')

    def publish(self, repo, number, text):
        if number != self.policy.issue or len(text) > 2048:
            raise ValueError('status outside bounds')
        posted = self.request('POST', self._path(repo) + '/issues/' + str(number) + '/comments', {'body': text})
        comment_id = posted.get('id')
        if not isinstance(comment_id, int) or comment_id < 1:
            raise RuntimeError('publication receipt missing')
        confirmed = self.request('GET', self._path(repo) + '/issues/comments/' + str(comment_id))
        if (confirmed.get('id') != comment_id or confirmed.get('body') != text or
            confirmed.get('issue_url') != 'https://api.github.com' + self._path(repo) + '/issues/' + str(number)):
            raise RuntimeError('publication verification failed')
        return comment_id
