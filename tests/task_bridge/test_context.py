"""Inert execution-context tests; no Hermes or GitHub child is launched."""
import hashlib
import json
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from signal_desk.task_bridge.context import (
    ExecutionContext, load_execution_context, validate_execution_context,
    write_task_context, trusted_context_prompt,
    _bounded_run,
)


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.state = self.root / 'state'
        self.state.mkdir(mode=0o700)
        requirements = b'pytest==8.3.3\n'
        (self.source / 'requirements.txt').write_bytes(requirements)
        self.digest = hashlib.sha256(requirements).hexdigest()
        self.venv = self.root / 'private-venv'
        (self.venv / 'bin').mkdir(parents=True, mode=0o700)
        self.venv.chmod(0o700)
        (self.venv / 'pyvenv.cfg').write_text('home = /usr/bin\n')
        self.python = self.venv / 'bin' / 'python'
        self.python.write_text('#!/bin/sh\nprintf OK\n')
        self.python.chmod(0o700)
        self.runner = 'a' * 40
        self.record = self.root / 'approved.json'
        self.record.write_text(json.dumps({'test_python': str(self.python),
                                           'requirements_sha256': self.digest,
                                           'runner_commit': self.runner,
                                           'python_version': '3.14.9',
                                           'pytest_version': '8.3.3'}))
        self.record.chmod(0o600)

    def test_private_record_is_bounded_owned_and_separate(self):
        context = load_execution_context(self.record, self.source, self.state)
        self.assertEqual(context.test_python, str(self.python))
        self.record.chmod(0o644)
        with self.assertRaisesRegex((ValueError, PermissionError), 'private'):
            load_execution_context(self.record, self.source, self.state)
        self.record.chmod(0o600)
        symlink = self.root / 'alias.json'
        symlink.symlink_to(self.record)
        with self.assertRaises(OSError):
            load_execution_context(symlink, self.source, self.state)
        self.record.write_bytes(b'x' * 2049)
        with self.assertRaisesRegex(ValueError, 'bound'):
            load_execution_context(self.record, self.source, self.state)

    def test_missing_or_mismatched_context_stops_before_interpreter_execution(self):
        self.record.unlink()
        with self.assertRaises(OSError):
            load_execution_context(self.record, self.source, self.state)
        self.record.write_text(json.dumps({'test_python': str(self.python),
                                           'requirements_sha256': '0' * 64,
                                           'runner_commit': self.runner,
                                           'python_version': '3.14.9',
                                           'pytest_version': '8.3.3'}))
        self.record.chmod(0o600)
        context = load_execution_context(self.record, self.source, self.state)
        with self.assertRaisesRegex(ValueError, 'requirements'):
            validate_execution_context(context, self.source, self.runner,
                                       backend_runner=lambda: 'local', runner=lambda *a, **kw: self.fail('executed'))
        self.python.unlink()
        with self.assertRaisesRegex(ValueError, 'interpreter'):
            validate_execution_context(ExecutionContext(str(self.python), self.digest, self.runner, '3.14.9', '8.3.3'),
                                       self.source, self.runner, backend_runner=lambda: 'local',
                                       runner=lambda *a, **kw: self.fail('executed'))

    def test_interpreter_inside_source_or_worker_state_is_not_approved(self):
        for path in (self.source / 'venv' / 'bin' / 'python',
                     self.state / 'venv' / 'bin' / 'python'):
            with self.subTest(path=path):
                self.record.write_text(json.dumps({'test_python': str(path),
                                                   'requirements_sha256': self.digest,
                                                   'runner_commit': self.runner,
                                                   'python_version': '3.14.9',
                                                   'pytest_version': '8.3.3'}))
                with self.assertRaisesRegex(ValueError, 'interpreter.*outside'):
                    load_execution_context(self.record, self.source, self.state)

    def test_source_local_alias_to_external_interpreter_is_still_rejected(self):
        alias = self.source / 'venv' / 'bin' / 'python'
        alias.parent.mkdir(parents=True)
        alias.symlink_to(self.python)
        self.record.write_text(json.dumps({'test_python': str(alias),
                                           'requirements_sha256': self.digest,
                                           'runner_commit': self.runner,
                                           'python_version': '3.14.9',
                                           'pytest_version': '8.3.3'}))
        with self.assertRaisesRegex(ValueError, 'interpreter.*outside'):
            load_execution_context(self.record, self.source, self.state)

    def test_preflight_checks_existing_interpreter_and_pip_without_shell(self):
        calls = []
        def inert_runner(argv, **kwargs):
            calls.append(argv)
            if '-c' in argv:
                return SimpleNamespace(returncode=0, stdout=json.dumps({
                    'version': '3.14.9', 'pytest': '8.3.3',
                    'prefix': str(self.venv)}), stderr='')
            return SimpleNamespace(returncode=0, stdout='No broken requirements found.\n', stderr='')
        context = load_execution_context(self.record, self.source, self.state)
        validate_execution_context(context, self.source, self.runner,
                                   backend_runner=lambda: 'local', runner=inert_runner)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][:3], [str(self.python), '-I', '-B'])
        self.assertEqual(calls[1], [str(self.python), '-I', '-B', '-m', 'pip', 'check'])
        with self.assertRaisesRegex(ValueError, 'backend'):
            validate_execution_context(context, self.source, self.runner,
                                       backend_runner=lambda: 'docker', runner=lambda *a, **kw: self.fail('executed'))

    def test_real_interpreter_probe_capture_is_bounded_before_memory_growth(self):
        result = _bounded_run([sys.executable, '-B', '-c', 'print("ok")'], timeout=5)
        self.assertEqual((result.returncode, result.stdout.strip()), (0, 'ok'))
        with self.assertRaisesRegex(ValueError, 'output bound'):
            _bounded_run([sys.executable, '-B', '-c', 'print("x" * 10000)'], timeout=5)

    def test_private_handoff_and_explicit_quoted_interpreter_survive_scrubbed_env(self):
        worktree = self.state / 'worktrees' / 'run'
        worktree.mkdir(parents=True)
        context = load_execution_context(self.record, self.source, self.state)
        handoff = write_task_context(self.state, worktree, context)
        self.assertEqual(handoff.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(handoff.read_text())['task_worktree'], str(worktree))
        with self.assertRaises(FileExistsError):
            write_task_context(self.state, worktree, context)
        text = trusted_context_prompt(context, worktree)
        self.assertIn(str(self.python), text)
        self.assertIn(str(worktree), text)
        self.assertNotIn('SIGNAL_DESK_TEST_PYTHON', text)
        self.assertIn(shlex.quote(str(self.python)), text)
        test_line = text.split('Only after that preflight succeeds, test with the explicit interpreter:\n', 1)[1].splitlines()[0]
        self.assertTrue(test_line.startswith(f'cd -- {shlex.quote(str(worktree))} && '))
        # No custom env or login PATH: only the quoted absolute executable works.
        weird = self.root / 'venv $(touch NEVER) with spaces'
        weird.mkdir()
        executable = weird / "python'unsafe"
        executable.write_text('#!/bin/sh\nprintf PROBE_OK\n')
        executable.chmod(0o700)
        rendered = trusted_context_prompt(ExecutionContext(str(executable), self.digest, self.runner, '3.14.9', '8.3.3'), worktree)
        self.assertIn(shlex.quote(str(executable)), rendered)
        command = rendered.split('Read-only terminal preflight: ', 1)[1].splitlines()[0]
        result = subprocess.run(['/bin/sh', '-c', command],
                                env={'PATH': '/usr/bin:/bin'}, capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout, 'PROBE_OK')
        self.assertFalse((self.root / 'NEVER').exists())


if __name__ == '__main__':
    unittest.main()
