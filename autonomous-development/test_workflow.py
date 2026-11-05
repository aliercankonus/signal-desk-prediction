#!/usr/bin/env python3
"""Local-only tests: fake Hermes launches and an isolated SQLite store; no model calls."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import pty
import shutil
import subprocess
import tempfile
import unittest

BASE = Path(__file__).resolve().parent
SCRATCH = Path('/opt/data/cache/scratch')


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        SCRATCH.mkdir(parents=True, exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(prefix='task-workflow-test-', dir=SCRATCH)
        cls.base = Path(cls.temp.name)
        cls.repo = cls.base / 'repo'
        cls.repo.mkdir()
        subprocess.run(['git', '-C', str(cls.repo), 'init', '-q'], check=True)
        (cls.repo / 'tracked.txt').write_text('base\n')
        subprocess.run(['git', '-C', str(cls.repo), 'add', 'tracked.txt'], check=True)
        subprocess.run(['git', '-C', str(cls.repo), '-c', 'user.name=Test',
                        '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'base'], check=True)
        (cls.repo / 'tracked.txt').write_text('base\nuncommitted\n')
        cls.brief = cls.base / 'brief.md'
        cls.brief.write_text('Fixture objective: check branch and tests.\n')
        project = cls.repo.name + '-' + hashlib.sha256(str(cls.repo).encode()).hexdigest()[:10]
        cls.cp_dir = Path('/opt/data/development-checkpoints') / project

    @classmethod
    def tearDownClass(cls):
        # Only this test's unique project directory and temporary fixture are removed.
        if cls.cp_dir.exists():
            shutil.rmtree(cls.cp_dir)
        cls.temp.cleanup()

    def launcher(self, *args, env=None, tty=False):
        command = ['python3', str(BASE / 'task_session.py'), *args]
        if tty:
            master, slave = pty.openpty()
            try:
                result = subprocess.run(command, stdin=slave, stdout=slave, stderr=slave,
                                        env=env, timeout=20)
            finally:
                os.close(slave)
                os.close(master)
            return result
        return subprocess.run(command, capture_output=True, text=True, env=env, timeout=20)

    def start_args(self):
        return ('start', '--repo', str(self.repo), '--task', 'fixture', '--brief', str(self.brief))

    def test_fresh_dry_run_and_non_tty_guard(self):
        result = self.launcher(*self.start_args(), '--dry-run')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['argv'][:5], ['hermes', 'chat', '--in', str(self.repo), '--tui'])
        self.assertTrue(data['fresh'])
        self.assertIn('-q', data['argv'])
        self.assertNotIn('--resume', data['argv'])
        self.assertNotIn('--continue', data['argv'])
        self.assertIn(str(self.brief), data['seed'])
        self.assertNotIn('Fixture objective:', data['seed'])
        self.assertEqual(self.launcher(*self.start_args()).returncode, 2)

    def test_checkpoint_dirty_git_and_secret_refusal(self):
        cp = BASE / 'checkpoint.py'
        common = ['python3', str(cp), '--repo', str(self.repo), '--task', 'unit-checkpoint',
                  '--tests', 'pytest: 2 passed', '--decisions', 'keep API', '--remaining', 'one dirty file',
                  '--output-root', str(self.base / 'checkpoints')]
        result = subprocess.run(common, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        path = Path(result.stdout.strip())
        text = path.read_text()
        self.assertIn('Tests: pytest: 2 passed', text)
        self.assertIn('Decisions: keep API', text)
        self.assertIn('Remaining: one dirty file', text)
        self.assertIn('Uncommitted changes: yes (preserved)', text)
        self.assertIn(subprocess.check_output(['git', '-C', str(self.repo), 'rev-parse', 'HEAD'], text=True).strip(), text)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertNotEqual(subprocess.run(common, capture_output=True).returncode, 0)
        self.assertEqual(path.read_text(), text)
        self.assertEqual(subprocess.check_output(['git', '-C', str(self.repo), 'status', '--porcelain'], text=True),
                         ' M tracked.txt\n')
        secret = subprocess.run(['python3', str(cp), '--repo', str(self.repo), '--task', 'secret-attempt',
                                 '--tests', 'not run: fixture', '--decisions', 'api_key=sk-' + 'x' * 24,
                                 '--remaining', 'none', '--output-root', str(self.base / 'checkpoints')],
                                capture_output=True, text=True)
        self.assertNotEqual(secret.returncode, 0)
        self.assertIn('checkpoint appears to contain a credential', secret.stderr)
        self.assertNotIn('sk-' + 'x' * 24, secret.stderr)
        self.assertFalse((path.parent / 'secret-attempt.md').exists())

    def test_only_selected_checkpoint_and_explicit_resume(self):
        self.cp_dir.mkdir(parents=True, exist_ok=False)
        selected = self.cp_dir / 'selected.md'
        selected.write_text('selected only\n')
        result = self.launcher(*self.start_args(), '--checkpoint', str(selected), '--dry-run')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertIn(str(selected), data['seed'])
        self.assertNotIn('selected only', data['seed'])
        foreign = self.base / 'wrong.md'
        foreign.write_text('wrong project\n')
        self.assertEqual(self.launcher(*self.start_args(), '--checkpoint', str(foreign), '--dry-run').returncode, 2)
        resume = self.launcher('resume', '--repo', str(self.repo), '--session', 'local-fixture-id', '--dry-run')
        self.assertEqual(resume.returncode, 0, resume.stderr)
        self.assertEqual(json.loads(resume.stdout)['argv'][-2:], ['--resume', 'local-fixture-id'])
        self.assertIsNone(json.loads(resume.stdout)['seed'])

    def test_interactive_invocation_uses_fake_hermes(self):
        bin_dir = self.base / 'bin'
        bin_dir.mkdir(exist_ok=True)
        fake = bin_dir / 'hermes'
        fake.write_text('#!/usr/bin/env python3\nimport json,os,sys\n'
                        'with open(os.environ["TASK_CAPTURE"], "w") as f:\n'
                        ' json.dump({"args":sys.argv[1:],"cwd":os.getcwd()},f)\n')
        fake.chmod(0o700)
        capture = self.base / 'captured.json'
        env = {**os.environ, 'PATH': str(bin_dir) + os.pathsep + os.environ['PATH'],
               'TASK_CAPTURE': str(capture)}
        result = self.launcher(*self.start_args(), env=env, tty=True)
        self.assertEqual(result.returncode, 0)
        data = json.loads(capture.read_text())
        self.assertEqual(data['cwd'], str(self.repo))
        self.assertIn('-q', data['args'])
        self.assertNotIn('--resume', data['args'])
        self.assertNotIn('--continue', data['args'])
        result = self.launcher('resume', '--repo', str(self.repo), '--session', 'local-fixture-id',
                               env=env, tty=True)
        self.assertEqual(result.returncode, 0)
        data = json.loads(capture.read_text())
        self.assertEqual(data['args'][-2:], ['--resume', 'local-fixture-id'])
        self.assertNotIn('-q', data['args'])

    def test_native_session_store_isolation(self):
        # The same SessionDB implementation used by Hermes, but on a fixture DB.
        from hermes_state import SessionDB
        db = SessionDB(self.base / 'fixture-state.db')
        try:
            db.create_session('fixture-task-a', 'cli')
            db.create_session('fixture-task-b', 'cli')
            db.append_message('fixture-task-a', 'user', 'A-only text')
            db.append_message('fixture-task-b', 'user', 'B-only text')
            self.assertEqual([m['content'] for m in db.get_messages('fixture-task-a')], ['A-only text'])
            self.assertEqual([m['content'] for m in db.get_messages('fixture-task-b')], ['B-only text'])
            self.assertIsNotNone(db.get_session('fixture-task-a'))
            self.assertIsNotNone(db.get_session('fixture-task-b'))
        finally:
            db.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
