import os
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from signal_desk.task_bridge.adapters import HermesAgent, GitHubREST
from signal_desk.task_bridge.bridge import Policy, draft_title, draft_body


POLICY = Policy("aliercankonus/signal-desk-prediction", 101, "a" * 64, "a930a3c715635341e62538a3cc15a260162f6be9", "review-task-101")

def inert_context(root, runner_commit):
    path = Path(root) / 'context.json'
    path.write_text(json.dumps({'test_python': str(Path(root) / 'venv' / 'bin' / 'python'),
                                'requirements_sha256': 'a' * 64, 'runner_commit': runner_commit,
                                'python_version': '3.14.9', 'pytest_version': '8.3.3'}))
    path.chmod(0o600)
    return path


class AdapterTests(unittest.TestCase):
    def test_task_draft_post_requires_exact_remote_head_and_fixed_payload(self):
        calls = []
        remote = {'sha': 'e' * 40}
        def request(method, path, payload=None):
            calls.append((method, path, payload))
            if path.endswith('/git/ref/heads/' + POLICY.branch):
                return {'ref': 'refs/heads/' + POLICY.branch,
                        'object': {'type': 'commit', 'sha': remote['sha']}}
            if method == 'POST':
                return {'number': 42}
            raise AssertionError(path)
        adapter = GitHubREST(POLICY, request=request)
        with self.assertRaisesRegex(ValueError, 'remote|head'):
            adapter.create_task_draft(POLICY.repo, POLICY.branch, 'f' * 40)
        self.assertFalse(any(method == 'POST' for method, _, _ in calls))
        remote['sha'] = 'f' * 40
        self.assertEqual(adapter.create_task_draft(POLICY.repo, POLICY.branch, 'f' * 40), 42)
        posts = [payload for method, _, payload in calls if method == 'POST']
        self.assertEqual(posts, [{'title': draft_title(POLICY), 'body': draft_body(POLICY),
                                  'head': POLICY.branch, 'base': 'main', 'draft': True,
                                  'maintainer_can_modify': False}])
        self.assertNotIn('/private/', str(posts))

    def test_task_draft_reuses_only_single_exact_open_draft_after_readback(self):
        head = 'f' * 40
        url = 'https://github.com/aliercankonus/signal-desk-prediction/pull/42'
        detail = {'number': 42, 'state': 'open', 'draft': True,
                  'title': draft_title(POLICY), 'body': draft_body(POLICY), 'html_url': url,
                  'head': {'sha': head, 'ref': POLICY.branch, 'repo': {'full_name': POLICY.repo}},
                  'base': {'ref': 'main', 'repo': {'full_name': POLICY.repo}}}
        candidates = [detail]
        calls = []
        def request(method, path, payload=None):
            calls.append((method, path))
            if path.endswith('/git/ref/heads/' + POLICY.branch):
                return {'ref': 'refs/heads/' + POLICY.branch, 'object': {'type': 'commit', 'sha': head}}
            if 'state=all' in path and '/pulls?' in path:
                return candidates
            if path.endswith('/pulls/42'):
                return detail
            raise AssertionError(path)
        adapter = GitHubREST(POLICY, request=request)
        adapter.draft_pr = lambda repo, branch: {
            'number': 42, 'title': detail['title'], 'body': detail['body'],
            'url': url, 'draft': True, 'head': head, 'target_branch': 'main',
            'target_repo': POLICY.repo, 'pinned_start': POLICY.base,
            'target_tip': 'd' * 40, 'ci_head': head, 'ci': 'unknown'}
        self.assertEqual(adapter.task_draft(POLICY.repo, POLICY.branch, head)['target_tip'], 'd'*40)
        self.assertTrue(all(method == 'GET' for method, _ in calls))
        candidates.clear()
        self.assertIsNone(adapter.task_draft(POLICY.repo, POLICY.branch, head))
        candidates.extend([detail, detail.copy()])
        with self.assertRaisesRegex(ValueError, 'multiple'):
            adapter.task_draft(POLICY.repo, POLICY.branch, head)
        candidates.pop()
        for key, value in (('state', 'closed'), ('draft', False), ('title', 'issue prose'),
                           ('body', 'Refs #101\nextra text')):
            with self.subTest(key=key):
                before = detail[key]
                detail[key] = value
                with self.assertRaisesRegex(ValueError, 'conflicting'):
                    adapter.task_draft(POLICY.repo, POLICY.branch, head)
                detail[key] = before
        detail['head']['sha'] = 'e' * 40
        with self.assertRaisesRegex(ValueError, 'conflicting'):
            adapter.task_draft(POLICY.repo, POLICY.branch, head)

    def test_agent_rejects_missing_or_mismatched_remote_and_dirty_worktree(self):
        for failure in ('absent', 'mismatch', 'dirty', 'branch'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                state = root / 'state'
                state.mkdir(mode=0o700)
                class Inert(HermesAgent):
                    def execute(self, argv, timeout=630):
                        return None
                agent = Inert(root / 'source', state, POLICY,
                              help_runner=lambda: ' '.join(HermesAgent.FLAGS),
                              context_path=inert_context(root, POLICY.base),
                              context_validator=lambda *args: args[0])
                def git(args):
                    if 'get-url' in args:
                        return 'https://github.com/' + POLICY.repo + '.git'
                    if 'cat-file' in args:
                        return 'commit'
                    if 'show-ref' in args:
                        raise subprocess.CalledProcessError(1, args)
                    if args[-2:] in (['var', 'GIT_AUTHOR_IDENT'], ['var', 'GIT_COMMITTER_IDENT']):
                        return 'Synthetic reviewer <reviewer@example.invalid> 0 +0000'
                    if args[:2] == ['worktree', 'add']:
                        Path(args[4]).mkdir(parents=True)
                        return ''
                    if 'symbolic-ref' in args:
                        return 'other' if failure == 'branch' else POLICY.branch
                    if 'status' in args:
                        return '?? unexpected.txt' if failure == 'dirty' else ''
                    if args[:2] == ['ls-remote', '--exit-code']:
                        if failure == 'absent':
                            raise subprocess.CalledProcessError(2, args)
                        return ('e' if failure == 'mismatch' else 'f') * 40 + '\trefs/heads/' + POLICY.branch
                    if 'rev-parse' in args:
                        return 'f'*40 if args[-1] == 'HEAD' else POLICY.base
                    return ''
                agent.git_runner = git
                with self.assertRaisesRegex(ValueError, 'pushed|clean|branch'):
                    agent.run('synthetic', state / 'worktrees' / 'run')

    def test_agent_rechecks_fixed_origin_after_child_before_remote_readback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / 'state'
            state.mkdir(mode=0o700)
            class Inert(HermesAgent):
                def execute(self, argv, timeout=630):
                    return None
            agent = Inert(root / 'source', state, POLICY,
                          help_runner=lambda: ' '.join(HermesAgent.FLAGS),
                          context_path=inert_context(root, POLICY.base),
                          context_validator=lambda *args: args[0])
            reads = []
            def git(args):
                if 'get-url' in args:
                    reads.append(args)
                    return ('https://github.com/' + POLICY.repo + '.git' if len(reads) == 1
                            else 'https://github.com/other/repo.git')
                if 'cat-file' in args:
                    return 'commit'
                if 'show-ref' in args:
                    raise subprocess.CalledProcessError(1, args)
                if args[-2:] in (['var', 'GIT_AUTHOR_IDENT'], ['var', 'GIT_COMMITTER_IDENT']):
                    return 'Synthetic reviewer <reviewer@example.invalid> 0 +0000'
                if args[:2] == ['worktree', 'add']:
                    Path(args[4]).mkdir(parents=True)
                    return ''
                if 'symbolic-ref' in args:
                    return POLICY.branch
                if args[:2] == ['ls-remote', '--exit-code']:
                    self.fail('remote lookup reached after origin changed')
                if 'rev-parse' in args:
                    return 'f'*40 if args[-1] == 'HEAD' else POLICY.base
                return ''
            agent.git_runner = git
            with self.assertRaisesRegex(ValueError, 'repository|origin'):
                agent.run('synthetic', state / 'worktrees' / 'run')

    def test_child_cannot_publish_pinned_start_without_a_new_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / 'state'
            state.mkdir(mode=0o700)
            class Inert(HermesAgent):
                def execute(self, argv, timeout=630):
                    return None
            agent = Inert(root / 'source', state, POLICY,
                          help_runner=lambda: ' '.join(HermesAgent.FLAGS),
                          context_path=inert_context(root, POLICY.base),
                          context_validator=lambda *args: args[0])
            def git(args):
                if 'get-url' in args:
                    return 'https://github.com/' + POLICY.repo + '.git'
                if 'cat-file' in args:
                    return 'commit'
                if 'show-ref' in args:
                    raise subprocess.CalledProcessError(1, args)
                if args[-2:] in (['var', 'GIT_AUTHOR_IDENT'], ['var', 'GIT_COMMITTER_IDENT']):
                    return 'Synthetic reviewer <reviewer@example.invalid> 0 +0000'
                if args[:2] == ['worktree', 'add']:
                    Path(args[4]).mkdir(parents=True)
                    return ''
                if 'symbolic-ref' in args:
                    return POLICY.branch
                if args[:2] == ['ls-remote', '--exit-code']:
                    return POLICY.base + '\trefs/heads/' + POLICY.branch
                if 'rev-parse' in args:
                    return POLICY.base
                return ''
            agent.git_runner = git
            with self.assertRaisesRegex(ValueError, 'new commit|pinned start'):
                agent.run('synthetic', state / 'worktrees' / 'run')

    def test_child_cannot_publish_empty_commit_with_unchanged_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / 'state'
            state.mkdir(mode=0o700)
            class Inert(HermesAgent):
                def execute(self, argv, timeout=630):
                    return None
            agent = Inert(root / 'source', state, POLICY,
                          help_runner=lambda: ' '.join(HermesAgent.FLAGS),
                          context_path=inert_context(root, POLICY.base),
                          context_validator=lambda *args: args[0])
            def git(args):
                if 'get-url' in args:
                    return 'https://github.com/' + POLICY.repo + '.git'
                if 'cat-file' in args:
                    return 'commit'
                if 'show-ref' in args:
                    raise subprocess.CalledProcessError(1, args)
                if args[-2:] in (['var', 'GIT_AUTHOR_IDENT'], ['var', 'GIT_COMMITTER_IDENT']):
                    return 'Synthetic reviewer <reviewer@example.invalid> 0 +0000'
                if args[:2] == ['worktree', 'add']:
                    Path(args[4]).mkdir(parents=True)
                    return ''
                if 'symbolic-ref' in args:
                    return POLICY.branch
                if args[:2] == ['ls-remote', '--exit-code']:
                    return 'f'*40 + '\trefs/heads/' + POLICY.branch
                if 'rev-parse' in args:
                    return 'b'*40 if args[-1].endswith('^{tree}') else ('f'*40 if args[-1] == 'HEAD' else POLICY.base)
                return ''
            agent.git_runner = git
            with self.assertRaisesRegex(ValueError, 'tree|artifact|changes'):
                agent.run('synthetic', state / 'worktrees' / 'run')

    def test_adapters_reject_cross_task_issue_branch_and_missing_start(self):
        for number in (101, 102):
            policy = Policy(POLICY.repo, number, POLICY.body_digest, 'b' * 40,
                            f'review-task-{number}')
            calls = []
            def request(method, path, payload=None):
                calls.append((method, path))
                return {'number': number, 'body': 'synthetic', 'state': 'open'}
            gh = GitHubREST(policy, request=request)
            self.assertEqual(gh.issue(policy.repo, number)['number'], number)
            with self.assertRaises(ValueError):
                gh.issue(policy.repo, 22)
            with self.assertRaises(ValueError):
                gh.draft_pr(policy.repo, 'review-task-other')
            with self.assertRaises(ValueError):
                gh.issue('other/repo', number)
            self.assertEqual(len(calls), 1)
            agent = HermesAgent('/source', '/state', policy,
                                help_runner=lambda: ' '.join(HermesAgent.FLAGS))
            agent.git_runner = lambda args: ('https://github.com/' + policy.repo + '.git'
                                             if 'get-url' in args else 'missing')
            with self.assertRaisesRegex(ValueError, 'pinned base'):
                agent.preflight()

    def test_preflight_rejects_existing_reviewed_branch(self):
        agent = HermesAgent('/source', '/state', POLICY,
                            help_runner=lambda: ' '.join(HermesAgent.FLAGS))
        agent.git_runner = lambda args: ('https://github.com/' + POLICY.repo + '.git'
                                         if 'get-url' in args else 'commit')
        with self.assertRaisesRegex(ValueError, 'branch already exists'):
            agent.preflight()

    def test_real_git_preflight_accepts_absent_branch_and_rejects_occupied_branch_and_bad_commit(self):
        # Use the production Git subprocess path; only Hermes help is synthetic.
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / 'source'
            occupied = Path(directory) / 'occupied-worktree'
            def git(*args):
                return subprocess.run(['git', '-C', str(repo), *args],
                                      capture_output=True, text=True, check=True).stdout.strip()
            subprocess.run(['git', 'init', '-q', str(repo)], check=True,
                           capture_output=True, text=True)
            git('-c', 'user.name=synthetic', '-c', 'user.email=synthetic@example.invalid',
                'commit', '--allow-empty', '-qm', 'synthetic base')
            git('remote', 'add', 'origin', 'https://github.com/' + POLICY.repo + '.git')
            start = git('rev-parse', 'HEAD')
            policy = Policy(POLICY.repo, 101, POLICY.body_digest, start, 'review-task-101')
            agent = HermesAgent(repo, Path(directory) / 'state', policy,
                                help_runner=lambda: ' '.join(HermesAgent.FLAGS),
                                context_path=inert_context(directory, start),
                                context_validator=lambda *args: args[0])
            self.assertTrue(agent.preflight())
            git('worktree', 'add', '-q', '-b', policy.branch, str(occupied), start)
            with self.assertRaisesRegex(ValueError, 'branch already exists'):
                agent.preflight()
            unavailable = Policy(POLICY.repo, 101, POLICY.body_digest, '0' * 40,
                                 'new-reviewed-branch')
            missing_agent = HermesAgent(repo, Path(directory) / 'state', unavailable,
                                        help_runner=lambda: ' '.join(HermesAgent.FLAGS))
            with self.assertRaisesRegex(ValueError, 'pinned base commit unavailable'):
                missing_agent.preflight()
            blob = subprocess.run(['git', '-C', str(repo), 'hash-object', '-w', '--stdin'],
                                  input=b'not a commit', capture_output=True, check=True).stdout.decode().strip()
            wrong_kind = Policy(POLICY.repo, 101, POLICY.body_digest, blob,
                                'new-reviewed-branch')
            blob_agent = HermesAgent(repo, Path(directory) / 'state', wrong_kind,
                                     help_runner=lambda: ' '.join(HermesAgent.FLAGS))
            with self.assertRaisesRegex(ValueError, 'pinned base commit unavailable'):
                blob_agent.preflight()

    def test_preflight_does_not_treat_unexpected_git_error_as_absent_branch(self):
        agent = HermesAgent('/source', '/state', POLICY,
                            help_runner=lambda: ' '.join(HermesAgent.FLAGS))
        def git(args):
            if args[:2] == ['remote', 'get-url']:
                return 'https://github.com/' + POLICY.repo + '.git'
            if args[:2] == ['cat-file', '-t']:
                return 'commit'
            raise subprocess.CalledProcessError(128, ['git', *args])
        agent.git_runner = git
        with self.assertRaises(subprocess.CalledProcessError) as error:
            agent.preflight()
        self.assertEqual(error.exception.returncode, 128)

    def test_help_verification_requires_all_bounded_flags(self):
        help_text = '--query-file PATH --oneshot --quiet --in DIR --max-turns N --run-budget SECONDS'
        adapter = HermesAgent('/source', '/private', POLICY, help_runner=lambda: help_text)
        self.assertEqual(adapter.check(), True)
        self.assertEqual(adapter.command('/private/prompt', '/private/worktrees/run')[:2], ['hermes', 'chat'])
        with self.assertRaises(ValueError):
            HermesAgent('/source', '/private', POLICY, help_runner=lambda: '--oneshot').check()

    def test_missing_private_context_blocks_before_worktree_or_child(self):
        agent = HermesAgent('/source', '/state', POLICY,
                            help_runner=lambda: ' '.join(HermesAgent.FLAGS))
        agent.git_runner = lambda args: ('https://github.com/' + POLICY.repo + '.git'
                                         if 'get-url' in args else 'commit'
                                         if 'cat-file' in args else
                                         (_ for _ in ()).throw(subprocess.CalledProcessError(1, args))
                                         if 'show-ref' in args else POLICY.base)
        with self.assertRaisesRegex(ValueError, 'execution context'):
            agent.preflight()

    def test_once_cli_requires_private_context_before_any_effect_adapter(self):
        from contextlib import redirect_stderr
        from unittest.mock import patch
        from signal_desk.task_bridge.__main__ import main
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source'
            subprocess.run(['git', 'init', '-q', str(source)], check=True)
            auth = root / 'auth.json'
            auth.write_text(json.dumps({'repo': POLICY.repo, 'issue': POLICY.issue,
                                        'body_digest': POLICY.body_digest, 'base': POLICY.base,
                                        'branch': POLICY.branch}))
            auth.chmod(0o600)
            errors = __import__('io').StringIO()
            with patch('signal_desk.task_bridge.__main__.GitHubREST',
                       side_effect=AssertionError('network adapter reached')), \
                 patch('signal_desk.task_bridge.__main__.Bridge',
                       side_effect=AssertionError('bridge reached')), \
                 redirect_stderr(errors), self.assertRaises(SystemExit) as raised:
                main(['once', '--source', str(source), '--state', str(root / 'state'),
                      '--auth', str(auth), '--execute-hermes'])
            self.assertEqual(raised.exception.code, 2)
            self.assertIn('context', errors.getvalue())
            self.assertFalse((root / 'state').exists())

    def test_inert_real_git_handoff_is_private_and_prompt_quotes_explicit_interpreter(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, state = root / 'source', root / 'state'
            subprocess.run(['git', 'init', '-q', str(source)], check=True)
            def git(*args):
                return subprocess.run(['git', '-C', str(source), *args],
                                      capture_output=True, text=True, check=True).stdout.strip()
            git('-c', 'user.name=synthetic', '-c', 'user.email=synthetic@example.invalid',
                'commit', '--allow-empty', '-qm', 'base')
            git('remote', 'add', 'origin', 'https://github.com/' + POLICY.repo + '.git')
            base = git('rev-parse', 'HEAD')
            policy = Policy(POLICY.repo, 101, POLICY.body_digest, base, 'review-task-101')
            selected = str(root / "private interpreter's bin" / 'python')
            git('config', '--local', 'user.name', 'Synthetic reviewer')
            git('config', '--local', 'user.email', 'reviewer@example.invalid')
            context = root / 'context.json'
            context.write_text(json.dumps({'test_python': selected, 'requirements_sha256': 'a' * 64,
                                           'runner_commit': base, 'python_version': '3.14.9',
                                           'pytest_version': '8.3.3'}))
            context.chmod(0o600)
            state.mkdir(mode=0o700)
            calls = []
            class Inert(HermesAgent):
                def execute(self, argv, timeout=630):
                    calls.append(argv)
                    (state / 'worktrees' / 'run' / 'synthetic.md').write_text('inert child edit\n')
                    git('-C', str(state / 'worktrees' / 'run'), 'add', 'synthetic.md')
                    git('-C', str(state / 'worktrees' / 'run'), '-c', 'user.name=synthetic',
                        '-c', 'user.email=synthetic@example.invalid', 'commit',
                        '-qm', 'inert child commit')
            agent = Inert(source, state, policy, help_runner=lambda: ' '.join(HermesAgent.FLAGS),
                          context_path=context, context_validator=lambda *a: a[0])
            stages = []
            agent.stage_callback = lambda stage, invocation=None: stages.append(stage)
            real_git = agent.git_runner
            # The inert child cannot push; simulate only the remote-ref readback.
            agent.git_runner = lambda args: (git('-C', str(state / 'worktrees' / 'run'), 'rev-parse', 'HEAD') +
                                             '\trefs/heads/' + policy.branch
                                             if args[:2] == ['ls-remote', '--exit-code'] else real_git(args))
            target = state / 'worktrees' / 'run'
            result = agent.run('untrusted issue prose: python=bare; echo DANGER', target)
            self.assertEqual(stages, ['preflight', 'child_invocation', 'child_completion',
                                      'local_result_verification'])
            self.assertNotEqual(result['head'], base)
            self.assertEqual(result['head'], git('-C', str(target), 'rev-parse', 'HEAD'))
            self.assertEqual(len(calls), 1)
            handoff = state / 'execution-context.json'
            self.assertEqual(handoff.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(handoff.read_text())['task_worktree'], str(target))
            prompt = (state / 'prompt').read_text()
            self.assertLess(prompt.index('Approved test interpreter'), prompt.index('untrusted issue prose'))
            self.assertIn("'" + selected.replace("'", "'\"'\"'") + "'", prompt)
            self.assertNotIn('SIGNAL_DESK_TEST_PYTHON', prompt)
    def test_real_task_worktree_git_identity_blocks_before_agent_and_accepts_worktree_config(self):
        from unittest.mock import patch
        for mode in ('missing_both', 'author_only', 'committer_only', 'worktree'):
            configure = mode == 'worktree'
            with self.subTest(identity_mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                source, state = root / 'source', root / 'state'
                subprocess.run(['git', 'init', '-q', str(source)], check=True)
                def git(*args):
                    return subprocess.run(['git', '-C', str(source), *args],
                                          capture_output=True, text=True, check=True).stdout.strip()
                git('-c', 'user.name=synthetic', '-c', 'user.email=synthetic@example.invalid',
                    'commit', '--allow-empty', '-qm', 'base')
                git('remote', 'add', 'origin', 'https://github.com/' + POLICY.repo + '.git')
                base = git('rev-parse', 'HEAD')
                policy = Policy(POLICY.repo, POLICY.issue, POLICY.body_digest, base, POLICY.branch)
                context = root / 'context.json'
                context.write_text(json.dumps({'test_python': str(root / 'python'),
                                               'requirements_sha256': 'a' * 64,
                                               'runner_commit': base, 'python_version': '3.14.9',
                                               'pytest_version': '8.3.3'}))
                context.chmod(0o600)
                state.mkdir(mode=0o700)
                calls = []
                agent = HermesAgent(source, state, policy, help_runner=lambda: ' '.join(HermesAgent.FLAGS),
                                    context_path=context, context_validator=lambda *args: args[0])
                real_git = agent.git_runner
                seen_identity_fields = []
                def watched_git(args):
                    if args[-2:] in (['var', 'GIT_AUTHOR_IDENT'], ['var', 'GIT_COMMITTER_IDENT']):
                        self.assertIn('user.useConfigOnly=true', args)
                        seen_identity_fields.append(args[-1])
                    if args[:2] == ['ls-remote', '--exit-code']:
                        raise AssertionError('remote read reached without inert result')
                    result = real_git(args)
                    if configure and args[:2] == ['worktree', 'add']:
                        git('config', '--local', 'extensions.worktreeConfig', 'true')
                        target = state / 'worktrees' / 'run'
                        for key, value in (('user.name', 'Synthetic reviewer'),
                                           ('user.email', 'reviewer@example.invalid')):
                            subprocess.run(['git', '-C', str(target), 'config', '--worktree', key, value],
                                           check=True, capture_output=True)
                    return result
                agent.git_runner = watched_git
                def inert_execute(argv, timeout=630):
                    calls.append(argv)
                    if configure:
                        target = state / 'worktrees' / 'run'
                        (target / 'synthetic.md').write_text('inert result\n')
                        git('-C', str(target), 'add', 'synthetic.md')
                        git('-C', str(target), 'commit', '-qm', 'synthetic result')
                agent.execute = inert_execute
                with patch.dict(os.environ, {'GIT_CONFIG_GLOBAL': os.devnull,
                                             'GIT_CONFIG_SYSTEM': os.devnull}):
                    for key in ('GIT_AUTHOR_NAME', 'GIT_AUTHOR_EMAIL',
                                'GIT_COMMITTER_NAME', 'GIT_COMMITTER_EMAIL'):
                        os.environ.pop(key, None)
                    if mode == 'author_only':
                        os.environ.update(GIT_AUTHOR_NAME='Synthetic author',
                                          GIT_AUTHOR_EMAIL='author@example.invalid')
                    if mode == 'committer_only':
                        os.environ.update(GIT_COMMITTER_NAME='Synthetic committer',
                                          GIT_COMMITTER_EMAIL='committer@example.invalid')
                    if configure:
                        with self.assertRaisesRegex(AssertionError, 'inert result'):
                            agent.run('inert task', state / 'worktrees' / 'run')
                        self.assertEqual(len(calls), 1)
                        self.assertEqual(seen_identity_fields,
                                         ['GIT_AUTHOR_IDENT', 'GIT_COMMITTER_IDENT'])
                    else:
                        with self.assertRaisesRegex(ValueError, 'Git.*identity'):
                            agent.run('inert task', state / 'worktrees' / 'run')
                        self.assertEqual(calls, [])

    def test_child_termination_metadata_retains_numeric_exit_and_signal(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from signal_desk.task_bridge.adapters import AgentTerminationError
        for code, status, reason in ((os.CLD_EXITED, 7, 'exit_nonzero'),
                                     (os.CLD_KILLED, 15, 'signal'),
                                     (999, 19, 'unknown')):
            with self.subTest(reason=reason):
                class FakeChild:
                    pid = 314159
                    def wait(self, timeout=None):
                        return 0
                agent = HermesAgent('/source', '/state', POLICY)
                with patch('signal_desk.task_bridge.adapters.subprocess.Popen', return_value=FakeChild()), \
                     patch('signal_desk.task_bridge.adapters.os.waitid',
                           return_value=SimpleNamespace(si_code=code, si_status=status)), \
                     patch('signal_desk.task_bridge.adapters.os.killpg'):
                    with self.assertRaises(AgentTerminationError) as raised:
                        agent.execute(['/bin/false'], timeout=1)
                self.assertEqual(raised.exception.stop_reason, reason)
                self.assertEqual(agent.last_invocation['stop_reason'], reason)
                self.assertEqual(agent.last_invocation['exit_code'], status if reason == 'exit_nonzero' else None)
                self.assertEqual(agent.last_invocation['signal_number'], status if reason == 'signal' else None)
                self.assertGreaterEqual(agent.last_invocation['duration_ms'], 0)

    def test_timeout_kills_child_process_group(self):
        import sys
        with tempfile.TemporaryDirectory() as directory:
            pidfile = Path(directory) / 'child.pid'
            script = ("import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);"
                      "open(sys.argv[1],'w').write(str(p.pid));time.sleep(30)")
            adapter = HermesAgent('/source', directory, POLICY, help_runner=lambda: ' '.join(HermesAgent.FLAGS))
            with self.assertRaises(TimeoutError):
                adapter.execute([sys.executable, '-c', script, str(pidfile)], timeout=0.5)
            pid = int(pidfile.read_text())
            import time
            time.sleep(0.1)
            try:
                state = Path(f'/proc/{pid}/stat').read_text().split()[2]
            except FileNotFoundError:
                state = 'gone'
            self.assertIn(state, ('Z', 'gone'))
    def test_group_signals_precede_reaping_leader(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        import signal
        events = []
        class FakeChild:
            pid = 314159
            def wait(self, timeout=None):
                events.append(('wait', timeout))
                return 0
        with patch('signal_desk.task_bridge.adapters.subprocess.Popen', return_value=FakeChild()), \
             patch('signal_desk.task_bridge.adapters.os.waitid',
                   return_value=SimpleNamespace(si_code=os.CLD_EXITED, si_status=0)), \
             patch('signal_desk.task_bridge.adapters.os.killpg',
                   side_effect=lambda pid, sig: events.append(('killpg', sig))):
            HermesAgent('/source', '/state', POLICY).execute(['/bin/true'], timeout=1)
        self.assertTrue(events)
        self.assertEqual(events[0][0], 'killpg')
        self.assertIn(('killpg', signal.SIGKILL), events)

    def test_repeated_sigterm_during_cleanup_still_kills_and_reaps(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        import signal
        events = []
        class FakeChild:
            pid = 314159
            def wait(self, timeout=None):
                events.append('reap')
                return 0
        def group_signal(pid, sig):
            events.append(sig)
            if sig == signal.SIGTERM:
                os.kill(os.getpid(), signal.SIGTERM)
        with patch('signal_desk.task_bridge.adapters.subprocess.Popen', return_value=FakeChild()), \
             patch('signal_desk.task_bridge.adapters.os.waitid',
                   return_value=SimpleNamespace(si_code=os.CLD_EXITED, si_status=0)), \
             patch('signal_desk.task_bridge.adapters.os.killpg', side_effect=group_signal):
            HermesAgent('/source', '/state', POLICY).execute(['/bin/true'], timeout=1)
        self.assertEqual(events, [signal.SIGTERM, signal.SIGKILL, 'reap'])

    def test_sigterm_terminates_agent_process_group(self):
        import signal
        import sys
        import time
        with tempfile.TemporaryDirectory() as directory:
            pidfile = Path(directory) / 'grandchild.pid'
            agent_code = ("import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);"
                          "open(sys.argv[1],'w').write(str(p.pid));time.sleep(30)")
            supervisor = ("import sys; from signal_desk.task_bridge.adapters import HermesAgent;"
                          "HermesAgent('/source','/state',__import__('signal_desk.task_bridge.bridge',fromlist=['Policy']).Policy('aliercankonus/signal-desk-prediction',101,'a'*64,'a930a3c715635341e62538a3cc15a260162f6be9','review-task-101')).execute([sys.executable,'-c',sys.argv[2],sys.argv[1]],timeout=25)")
            proc = subprocess.Popen([sys.executable, '-c', supervisor, str(pidfile), agent_code],
                                    env={**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[2] / 'src')},
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            child_pid = None
            try:
                for _ in range(100):
                    if pidfile.exists():
                        child_pid = int(pidfile.read_text())
                        break
                    time.sleep(0.02)
                self.assertIsNotNone(child_pid)
                os.kill(proc.pid, signal.SIGTERM)
                proc.wait(timeout=5)
                time.sleep(0.1)
                try:
                    child_state = Path(f'/proc/{child_pid}/stat').read_text().split()[2]
                except FileNotFoundError:
                    child_state = 'gone'
                self.assertIn(child_state, ('Z', 'gone'))
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=5)
                if child_pid:
                    try:
                        os.kill(child_pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    def test_api_response_is_bounded_before_json_parse(self):
        import io
        adapter = GitHubREST(POLICY)
        with self.assertRaisesRegex(ValueError, 'response'):
            adapter._bounded_json(io.BytesIO(b' ' * 131073))
        self.assertEqual(adapter._bounded_json(io.BytesIO(b'{"ok":true}')), {'ok': True})

    def test_rest_adapter_reads_issue_pr_and_exact_head_status(self):
        calls = []
        def request(method, path, payload=None):
            calls.append((method, path, payload))
            if path.endswith('/issues/101'):
                return {'number': 101, 'body': 'body', 'state': 'open'}
            if '/pulls?' in path:
                return [{'number': 42, 'html_url': 'https://github.com/aliercankonus/signal-desk-prediction/pull/42',
                         'draft': True, 'head': {'sha': 'f'*40, 'ref': 'review-task-101',
                                                  'repo': {'full_name': 'aliercankonus/signal-desk-prediction'}},
                         'base': {'sha': 'a930a3c715635341e62538a3cc15a260162f6be9',
                                  'ref': 'main', 'repo': {'full_name': GitHubREST.REPO}}}]
            if '/git/ref/heads/main' in path:
                return {'ref': 'refs/heads/main', 'object': {'type': 'commit', 'sha': 'a930a3c715635341e62538a3cc15a260162f6be9'}}
            if '/compare/' in path:
                return {'status': 'ahead', 'merge_base_commit': {'sha': 'a930a3c715635341e62538a3cc15a260162f6be9'}}
            if '/check-runs?' in path:
                return {'check_runs': []}
            if '/actions/runs?' in path:
                return {'workflow_runs': []}
            if '/status' in path:
                return {'sha': 'f'*40, 'state': 'success', 'statuses': [{'state': 'success'}]}
            if '/comments/99' in path:
                return {'id': 99, 'body': 'safe status', 'issue_url': 'https://api.github.com/repos/aliercankonus/signal-desk-prediction/issues/101'}
            if method == 'POST':
                return {'id': 99}
            return {}
        gh = GitHubREST(POLICY, request=request)
        self.assertEqual(gh.issue('aliercankonus/signal-desk-prediction', 101)['body'], 'body')
        pr = gh.draft_pr('aliercankonus/signal-desk-prediction', 'review-task-101')
        self.assertEqual(pr['ci_head'], 'f'*40)
        gh.publish('aliercankonus/signal-desk-prediction', 101, 'safe status')
        self.assertEqual(calls[-1], ('GET', '/repos/aliercankonus/signal-desk-prediction/issues/comments/99', None))

    def test_draft_pr_accepts_moving_main_tip_without_changing_pinned_start(self):
        start = 'a930a3c715635341e62538a3cc15a260162f6be9'
        tip = 'd' * 40
        head = 'f' * 40
        paths = []
        def request(method, path, payload=None):
            paths.append(path)
            if '/pulls?' in path:
                return [{'html_url': 'https://github.com/aliercankonus/signal-desk-prediction/pull/42',
                         'draft': True, 'head': {'sha': head, 'ref': 'review-task-101',
                                                  'repo': {'full_name': GitHubREST.REPO}},
                         'base': {'sha': start, 'ref': 'main', 'repo': {'full_name': GitHubREST.REPO}},
                         'body': 'Refs #101'}]
            if '/git/ref/heads/main' in path:
                return {'ref': 'refs/heads/main', 'object': {'type': 'commit', 'sha': tip}}
            if '/compare/' in path:
                return {'status': 'ahead', 'merge_base_commit': {'sha': start}}
            if '/check-runs?' in path:
                return {'check_runs': []}
            if '/actions/runs?' in path:
                return {'workflow_runs': []}
            if '/status' in path:
                return {'sha': head, 'statuses': []}
            raise AssertionError(path)
        pr = GitHubREST(POLICY, request=request).draft_pr(GitHubREST.REPO, 'review-task-101')
        self.assertIsNotNone(pr)
        self.assertEqual(pr['pinned_start'], start)
        self.assertEqual(pr['target_tip'], tip)
        self.assertEqual(pr['target_branch'], 'main')
        self.assertEqual(pr['target_repo'], GitHubREST.REPO)
        self.assertTrue(any('/git/ref/heads/main' in path for path in paths))

    def test_draft_pr_rejects_wrong_target_branch_or_repository(self):
        for target_ref, target_repo in (('develop', GitHubREST.REPO), ('main', 'other/repo')):
            calls = []
            def request(method, path, payload=None):
                calls.append(path)
                if '/pulls?' in path:
                    return [{'draft': True, 'head': {'sha': 'f' * 40, 'ref': 'review-task-101',
                                                       'repo': {'full_name': GitHubREST.REPO}},
                             'base': {'sha': 'a930a3c715635341e62538a3cc15a260162f6be9',
                                      'ref': target_ref, 'repo': {'full_name': target_repo}}}]
                raise AssertionError('invalid target should stop before compare: ' + path)
            self.assertIsNone(GitHubREST(POLICY, request=request).draft_pr(GitHubREST.REPO, 'review-task-101'))
            self.assertEqual(len(calls), 1)

    def test_draft_pr_rejects_inconsistent_ancestry_evidence(self):
        start = 'a930a3c715635341e62538a3cc15a260162f6be9'
        head = 'f' * 40
        def request(method, path, payload=None):
            if '/pulls?' in path:
                return [{'draft': True, 'head': {'sha': head, 'ref': 'review-task-101',
                                                   'repo': {'full_name': GitHubREST.REPO}},
                         'base': {'sha': start, 'ref': 'main', 'repo': {'full_name': GitHubREST.REPO}}}]
            if '/git/ref/heads/main' in path:
                return {'ref': 'refs/heads/main', 'object': {'type': 'commit', 'sha': 'd' * 40}}
            if '/compare/' in path:
                return {'status': 'ahead', 'merge_base_commit': {'sha': '0' * 40}}
            raise AssertionError('inconsistent comparison should stop: ' + path)
        self.assertIsNone(GitHubREST(POLICY, request=request).draft_pr(GitHubREST.REPO, 'review-task-101'))

    def test_draft_pr_rejects_head_not_descended_from_pinned_base(self):
        head = 'e' * 40
        def request(method, path, payload=None):
            if '/pulls?' in path:
                return [{'html_url': 'https://github.com/aliercankonus/signal-desk-prediction/pull/42',
                         'draft': True, 'head': {'sha': head, 'ref': 'review-task-101',
                                                  'repo': {'full_name': 'aliercankonus/signal-desk-prediction'}},
                         'base': {'sha': 'a930a3c715635341e62538a3cc15a260162f6be9',
                                  'ref': 'main', 'repo': {'full_name': GitHubREST.REPO}}, 'body': 'Refs #101'}]
            if '/git/ref/heads/main' in path:
                return {'ref': 'refs/heads/main', 'object': {'type': 'commit', 'sha': 'd' * 40}}
            if '/compare/' in path:
                return {'status': 'diverged', 'merge_base_commit': {'sha': '0' * 40}}
            if '/check-runs?' in path:
                return {'check_runs': []}
            if '/actions/runs?' in path:
                return {'workflow_runs': []}
            if '/status' in path:
                return {'sha': head, 'statuses': []}
            raise AssertionError(path)
        self.assertIsNone(GitHubREST(POLICY, request=request).draft_pr('aliercankonus/signal-desk-prediction', 'review-task-101'))

    def test_exact_head_ci_prefers_check_runs_over_empty_legacy_status(self):
        head = 'e' * 40
        paths = []
        def request(method, path, payload=None):
            paths.append(path)
            if '/pulls?' in path:
                return [{'html_url': 'https://github.com/aliercankonus/signal-desk-prediction/pull/42',
                         'draft': True, 'head': {'sha': head, 'ref': 'review-task-101',
                                                  'repo': {'full_name': 'aliercankonus/signal-desk-prediction'}},
                         'base': {'sha': 'a930a3c715635341e62538a3cc15a260162f6be9',
                                  'ref': 'main', 'repo': {'full_name': GitHubREST.REPO}}, 'body': 'Refs #101'}]
            if '/git/ref/heads/main' in path:
                return {'ref': 'refs/heads/main', 'object': {'type': 'commit', 'sha': 'd' * 40}}
            if '/compare/' in path:
                return {'status': 'ahead', 'merge_base_commit': {'sha': 'a930a3c715635341e62538a3cc15a260162f6be9'}}
            if '/check-runs?' in path:
                return {'check_runs': [{'name': 'full-pytest', 'head_sha': head,
                                        'status': 'completed', 'conclusion': 'success'}]}
            if '/actions/runs?' in path:
                return {'workflow_runs': [{'name': 'Collector image tests', 'head_sha': head,
                                           'status': 'completed', 'conclusion': 'success'}]}
            if '/status' in path:
                return {'sha': head, 'state': 'pending', 'statuses': []}
            raise AssertionError(path)
        pr = GitHubREST(POLICY, request=request).draft_pr('aliercankonus/signal-desk-prediction', 'review-task-101')
        self.assertEqual(pr['ci'], 'success')
        self.assertTrue(any('/check-runs?' in path for path in paths))
        self.assertTrue(any('/actions/runs?' in path for path in paths))

    def test_preflight_requires_pinned_commit_object_not_literal_sha(self):
        adapter = HermesAgent('/source', '/state', POLICY, help_runner=lambda: ' '.join(HermesAgent.FLAGS))
        adapter.git_runner = lambda args: ('https://github.com/aliercankonus/signal-desk-prediction.git'
                                           if 'get-url' in args else 'missing')
        with self.assertRaisesRegex(ValueError, 'base|commit'):
            adapter.preflight()

    def test_agent_rejects_wrong_source_repository_before_worktree(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter = HermesAgent('/source', directory, POLICY, help_runner=lambda: ' '.join(HermesAgent.FLAGS))
            adapter.execute = lambda argv, timeout=630: None  # Never launch a real Hermes process in this test.
            calls = []
            def git(args):
                calls.append(args)
                return 'https://github.com/other/repository.git' if 'get-url' in args else 'a930a3c715635341e62538a3cc15a260162f6be9'
            adapter.git_runner = git
            with self.assertRaisesRegex(ValueError, 'repository'):
                adapter.run('frozen', str(Path(directory) / 'worktrees' / 'run'))
            self.assertFalse(any('add' in args for args in calls))

    def test_agent_rejects_symlinked_worktree_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / 'private'
            outside = Path(directory) / 'outside'
            state.mkdir()
            outside.mkdir()
            (state / 'worktrees').symlink_to(outside, target_is_directory=True)
            adapter = HermesAgent('/source', state, POLICY, help_runner=lambda: ' '.join(HermesAgent.FLAGS),
                                  context_path=inert_context(directory, POLICY.base),
                                  context_validator=lambda *args: args[0])
            adapter.execute = lambda argv, timeout=630: None  # Never launch a real Hermes process in this test.
            def git(args):
                if 'show-ref' in args:
                    raise subprocess.CalledProcessError(1, args)
                return ('https://github.com/aliercankonus/signal-desk-prediction.git' if 'get-url' in args else
                        'commit' if 'cat-file' in args else POLICY.base)
            adapter.git_runner = git
            with self.assertRaisesRegex(ValueError, 'symlink|worktree'):
                adapter.run('frozen', str(state / 'worktrees' / 'run'))

    def test_remote_reconciliation_reads_only_matching_run_statuses(self):
        run_id = 'f' * 32
        seen = []
        def request(method, path, payload=None):
            seen.append((method, path))
            if path == '/user':
                return {'login': 'authorized-writer'}
            return [{'id': 1, 'body': json.dumps({'run_id': run_id, 'status': 'queued'}),
                     'user': {'login': 'authorized-writer'}},
                    {'id': 2, 'body': 'untrusted narrative', 'user': {'login': 'authorized-writer'}},
                    {'id': 3, 'body': json.dumps({'run_id': 'other', 'status': 'review-ready'}),
                     'user': {'login': 'authorized-writer'}}]
        adapter = GitHubREST(POLICY, request=request)
        payload = json.dumps({'run_id': run_id, 'status': 'queued'})
        self.assertEqual(adapter.statuses(adapter.REPO, 101, run_id, {'queued': payload}),
                         [{'id': 1, 'status': 'queued'}])
        self.assertTrue(all(method == 'GET' for method, _ in seen))

    def test_reconcile_ignores_counterfeit_comment_author_and_payload(self):
        run_id = 'f' * 32
        expected = json.dumps({'status': 'queued', 'run_id': run_id, 'base': 'a930a3c715635341e62538a3cc15a260162f6be9'})
        def request(method, path, payload=None):
            if path == '/user':
                return {'login': 'authorized-writer'}
            return [{'id': 10, 'body': expected, 'user': {'login': 'outsider'}},
                    {'id': 11, 'body': expected + ' ', 'user': {'login': 'authorized-writer'}}]
        self.assertEqual(GitHubREST(POLICY, request=request).statuses(
            GitHubREST.REPO, 101, run_id, {'queued': expected}), [])

    def test_local_agent_result_rejects_non_descendant_head(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / 'private'
            state.mkdir(mode=0o700)
            class Inert(HermesAgent):
                def execute(self, argv, timeout=630):
                    return None
            adapter = Inert('/source', state, POLICY, help_runner=lambda: ' '.join(HermesAgent.FLAGS),
                            context_path=inert_context(directory, 'f' * 40),
                            context_validator=lambda *args: args[0])
            def fake_git(args):
                if 'get-url' in args:
                    return 'https://github.com/aliercankonus/signal-desk-prediction.git'
                if 'cat-file' in args:
                    return 'commit'
                if 'show-ref' in args:
                    raise subprocess.CalledProcessError(1, args)
                if args[-2:] in (['var', 'GIT_AUTHOR_IDENT'], ['var', 'GIT_COMMITTER_IDENT']):
                    return 'Synthetic reviewer <reviewer@example.invalid> 0 +0000'
                if 'merge-base' in args:
                    raise subprocess.CalledProcessError(1, args)
                if 'symbolic-ref' in args:
                    return POLICY.branch
                if args[:2] == ['worktree', 'add']:
                    Path(args[4]).mkdir(parents=True)
                if 'rev-parse' in args:
                    return 'f' * 40
                return ''
            adapter.git_runner = fake_git
            with self.assertRaisesRegex(ValueError, 'ancestor|base'):
                adapter.run('frozen', str(state / 'worktrees' / 'run'))

    def test_agent_prepares_new_pinned_worktree_and_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / 'private'
            state.mkdir(mode=0o700)
            calls = []
            class Inert(HermesAgent):
                def execute(self, argv, timeout=630):
                    calls.append(argv)
            adapter = Inert('/source', state, POLICY, help_runner=lambda: ' '.join(HermesAgent.FLAGS),
                            context_path=inert_context(directory, 'f' * 40),
                            context_validator=lambda *args: args[0])
            def fake_git(args):
                if 'get-url' in args:
                    return 'https://github.com/aliercankonus/signal-desk-prediction.git'
                if 'cat-file' in args:
                    return 'commit'
                if 'show-ref' in args:
                    raise subprocess.CalledProcessError(1, args)
                if args[-2:] in (['var', 'GIT_AUTHOR_IDENT'], ['var', 'GIT_COMMITTER_IDENT']):
                    return 'Synthetic reviewer <reviewer@example.invalid> 0 +0000'
                if 'rev-parse' in args:
                    if args[-1].endswith('^{tree}'):
                        return ('f' if args[-1] == 'HEAD^{tree}' else 'a') * 40
                    return 'f' * 40 if args[-1] == 'HEAD' else 'a930a3c715635341e62538a3cc15a260162f6be9'
                if 'symbolic-ref' in args:
                    return POLICY.branch
                if args[:2] == ['ls-remote', '--exit-code']:
                    return 'f' * 40 + '\trefs/heads/' + POLICY.branch
                if args[:2] == ['worktree', 'add']:
                    Path(args[4]).mkdir(parents=True)
                calls.append(args)
                return ''
            adapter.git_runner = fake_git
            worktree = str(state / 'worktrees' / 'run')
            result = adapter.run('frozen prompt', worktree)
            self.assertEqual(result['head'], 'f'*40)
            self.assertIn(['worktree', 'add', '-b', 'review-task-101', worktree, 'a930a3c715635341e62538a3cc15a260162f6be9'], calls)
            self.assertTrue((state / 'prompt').exists())
            with self.assertRaises(FileExistsError):
                adapter.run('frozen prompt', worktree)
    def test_doctor_cli_is_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / 'state'
            result = subprocess.run([os.environ.get('PYTHON', 'python3'), '-m', 'signal_desk.task_bridge',
                                     'doctor', '--state', str(state)], capture_output=True, text=True,
                                    env={**os.environ, 'PYTHONPATH': 'src'})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('queued', result.stdout)
            self.assertFalse(state.exists())
    def test_reconcile_cli_is_read_only_without_state(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / 'state'
            result = subprocess.run([os.environ.get('PYTHON', 'python3'), '-m', 'signal_desk.task_bridge',
                                     'reconcile', '--state', str(state)], capture_output=True, text=True,
                                    env={**os.environ, 'PYTHONPATH': 'src'})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['status'], 'queued')
            self.assertFalse(state.exists())

    def test_state_must_be_outside_repo_even_when_source_is_subdirectory(self):
        from signal_desk.task_bridge.__main__ import validate_checkout_paths
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / 'repo'
            (repo / 'src').mkdir(parents=True)
            subprocess.run(['git', 'init', str(repo)], check=True, capture_output=True)
            with self.assertRaisesRegex(ValueError, 'root|checkout'):
                validate_checkout_paths(repo / 'src', repo / 'private')

    def test_once_cli_rejects_state_symlink_before_network_or_agent(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'source'
            source.mkdir()
            actual = Path(directory) / 'actual'
            actual.mkdir(mode=0o700)
            link = Path(directory) / 'alias'
            link.symlink_to(actual, target_is_directory=True)
            result = subprocess.run([os.environ.get('PYTHON', 'python3'), '-m', 'signal_desk.task_bridge',
                                     'once', '--state', str(link), '--source', str(source), '--execute-hermes'],
                                    capture_output=True, text=True, env={**os.environ, 'PYTHONPATH': 'src'})
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('legacy bootstrap', result.stderr)


if __name__ == '__main__':
    unittest.main()
