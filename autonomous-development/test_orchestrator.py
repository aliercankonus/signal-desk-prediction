"""Offline orchestration tests; no real Hermes process or provider call."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from orchestrator import TaskStore, run_queue, git_fingerprint, write_checkpoint, verify_task, execute_task


class SubmitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='orchestrator-test-', dir='/opt/data/cache/scratch')
        self.root = Path(self.temp.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        subprocess.run(['git', '-C', str(self.repo), 'init', '-q'], check=True)
        subprocess.run(['git', '-C', str(self.repo), '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '--allow-empty', '-qm', 'fixture'], check=True)
        self.store = TaskStore(self.root / 'queue')

    def tearDown(self):
        self.temp.cleanup()

    def test_natural_language_creates_small_private_brief_and_queued_state(self):
        task = self.store.submit(self.repo, 'Fix parser edge cases and run tests.')
        brief = Path(task['brief'])
        self.assertEqual(task['status'], 'queued')
        self.assertIn('Fix parser edge cases and run tests.', brief.read_text())
        self.assertLess(len(brief.read_text()), 3000)
        self.assertEqual(brief.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.store.load(task['id'])['id'], task['id'])
        self.assertEqual(self.store.pending()[0]['id'], task['id'])

    def test_refuses_credentials_and_transcript_sized_requests(self):
        with self.assertRaises(ValueError):
            self.store.submit(self.repo, 'Use api_key=sk-' + 'x' * 24)
        with self.assertRaises(ValueError):
            self.store.submit(self.repo, 'x' * 2100)
        self.assertEqual(self.store.pending(), [])

    def test_related_task_stays_bound_to_same_repo_and_parent(self):
        parent = self.store.submit(self.repo, 'Build parser')
        child = self.store.submit(self.repo, 'Also add tests', related=parent['id'])
        self.assertEqual(child['related'], parent['id'])
        other = self.root / 'other'
        other.mkdir()
        subprocess.run(['git', '-C', str(other), 'init', '-q'], check=True)
        with self.assertRaises(ValueError):
            self.store.submit(other, 'Unrelated request', related=parent['id'])
    def test_cli_submit_and_status_are_offline(self):
        script = Path(__file__).with_name('orchestrator.py')
        proc = subprocess.run(['python3', str(script), '--store', str(self.store.root),
                               'submit', '--repo', str(self.repo), '--text', 'Fix parser'],
                              check=True, capture_output=True, text=True)
        task = json.loads(proc.stdout)
        self.assertEqual(task['status'], 'queued')
        status = subprocess.run(['python3', str(script), '--store', str(self.store.root), 'status'],
                                check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(status.stdout)[0]['id'], task['id'])

    def test_monitor_reports_only_counts_without_task_text_or_writes(self):
        from orchestrator import monitor_snapshot
        task = self.store.submit(self.repo, 'private fixture brief')
        before = (self.store.root / task['id'] / 'state.json').stat().st_mtime_ns
        snapshot = monitor_snapshot(self.store.root)
        self.assertEqual(snapshot, {'queued': 1, 'running': 0, 'blocked': 0, 'completed': 0})
        self.assertNotIn('private fixture brief', json.dumps(snapshot))
        self.assertEqual((self.store.root / task['id'] / 'state.json').stat().st_mtime_ns, before)

    def test_worker_rejects_unmounted_repository_before_model_launch(self):
        task = self.store.submit(self.repo, 'Never run outside the mounted repo')
        other = self.root / 'approved'
        other.mkdir()
        subprocess.run(['git', '-C', str(other), 'init', '-q'], check=True)
        calls = []
        result = run_queue(self.store, lambda *args: calls.append(args),
                           lambda item: self.fail('must not verify'),
                           lambda *args: self.fail('must not checkpoint'),
                           allowed_repo=other)
        self.assertEqual(calls, [])
        self.assertEqual(self.store.load(task['id'])['status'], 'queued')
        self.assertIn('repository', result['stopped'])

    def test_running_crash_state_prevents_next_task_launch(self):
        first = self.store.submit(self.repo, 'First')
        second = self.store.submit(self.repo, 'Second')
        first['status'] = 'running'
        self.store.save(first)
        result = run_queue(self.store, lambda *args: self.fail('must not start while stale running'),
                           lambda task: self.fail('must not verify'), lambda *args: self.fail('must not checkpoint'))
        self.assertEqual(result['completed'], 0)
        self.assertEqual(self.store.load(second['id'])['status'], 'queued')
        self.assertIn('running', result['stopped'])
    def test_quota_acknowledgment_is_explicit_and_does_not_retry_blocked_task(self):
        task = self.store.submit(self.repo, 'First')
        task.update(status='blocked', failure_code='quota')
        self.store.save(task)
        script = Path(__file__).with_name('orchestrator.py')
        command = ['python3', str(script), '--store', str(self.store.root), 'ack-quota', '--task', task['id']]
        accepted = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertTrue(self.store.load(task['id'])['quota_ack_ns'])
        self.assertEqual(self.store.quota_pauses(), [])
        self.assertEqual(self.store.load(task['id'])['status'], 'blocked')
    def test_nonquota_failure_stays_paused_across_new_supervisor_until_acknowledged(self):
        first = self.store.submit(self.repo, 'First')
        second = self.store.submit(self.repo, 'Second')
        first.update(status='blocked', failure_code='verification')
        self.store.save(first)
        calls = []
        stopped = run_queue(TaskStore(self.store.root), lambda *args: calls.append(args),
                            lambda task: self.fail('no verification'),
                            lambda *args: self.fail('no checkpoint'))
        self.assertEqual(calls, [])
        self.assertIn('pause', stopped['stopped'])
        self.assertEqual(self.store.load(second['id'])['status'], 'queued')
        self.store.acknowledge_block(first['id'])
        self.assertEqual(self.store.load(first['id'])['status'], 'blocked')
        self.assertEqual(self.store.pauses(), [])
    def test_watch_mode_idles_instead_of_restart_loop_on_quota_pause(self):
        blocked = self.store.submit(self.repo, 'First')
        blocked.update(status='blocked', failure_code='quota')
        self.store.save(blocked)
        later = self.store.submit(self.repo, 'Never launch while paused')
        script = Path(__file__).with_name('orchestrator.py')
        process = subprocess.Popen(['python3', str(script), '--store', str(self.store.root),
                                    'run', '--watch'], stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
        try:
            import time
            time.sleep(1)
            self.assertIsNone(process.poll(), 'watcher exited and would restart-loop under Docker')
            self.assertEqual(self.store.load(later['id'])['status'], 'queued')
        finally:
            process.terminate()
            process.wait(timeout=5)
    def test_ack_block_cli_releases_only_nonquota_pause(self):
        blocked = self.store.submit(self.repo, 'Verification failed')
        blocked.update(status='blocked', failure_code='verification')
        self.store.save(blocked)
        quota = self.store.submit(self.repo, 'Quota failure')
        quota.update(status='blocked', failure_code='quota')
        self.store.save(quota)
        script = Path(__file__).with_name('orchestrator.py')
        base = ['python3', str(script), '--store', str(self.store.root), 'ack-block', '--task']
        self.assertNotEqual(subprocess.run(base + [quota['id']], capture_output=True).returncode, 0)
        self.assertEqual(subprocess.run(base + [blocked['id']], capture_output=True).returncode, 0)
        self.assertEqual(self.store.pauses(), [])
        self.assertEqual(len(self.store.quota_pauses()), 1)
    def test_second_watcher_refuses_same_persistent_queue_lock(self):
        script = Path(__file__).with_name('orchestrator.py')
        cmd = ['python3', str(script), '--store', str(self.store.root), 'run', '--watch']
        first = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            import time
            for _ in range(50):
                if (self.store.root / '.runner.lock').exists():
                    break
                time.sleep(0.1)
            self.assertTrue((self.store.root / '.runner.lock').exists())
            second = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            self.assertNotEqual(second.returncode, 0)
            self.assertIn('another supervisor', second.stderr)
            self.assertIsNone(first.poll())
        finally:
            first.terminate()
            first.wait(timeout=5)


class RunTests(unittest.TestCase):
    setUp = SubmitTests.setUp
    tearDown = SubmitTests.tearDown
    def test_successive_independent_tasks_are_fresh_and_related_one_resumes(self):
        a = self.store.submit(self.repo, 'Implement A')
        b = self.store.submit(self.repo, 'Implement B')
        c = self.store.submit(self.repo, 'Add A tests', related=a['id'])
        calls = []

        def execute(task, resume_id):
            calls.append((task['id'], resume_id))
            (self.repo / task['id']).write_text('changed\n')
            sid = 'session-a' if task['id'] in (a['id'], c['id']) else 'session-b'
            return {'exit_code': 0, 'session_id': sid,
                    'text': json.dumps({'status': 'complete', 'decisions': 'Small fix', 'remaining': 'none'})}

        def verify(task):
            return {'ok': True, 'summary': 'PASS: pytest -q (exit 0)'}

        def checkpoint(task, tests, decisions, remaining, session_id):
            return write_checkpoint(task, tests, decisions, remaining, session_id,
                                    output_root=self.root / 'checkpoints')

        result = run_queue(self.store, execute, verify, checkpoint, max_tasks=3)
        self.assertEqual(result['completed'], 3)
        self.assertEqual(calls, [(a['id'], None), (b['id'], None), (c['id'], 'session-a')])
        self.assertEqual(len({self.store.load(t['id'])['session_id'] for t in (a, b, c)}), 2)
        for task in (a, b, c):
            done = self.store.load(task['id'])
            self.assertEqual(done['status'], 'completed')
            self.assertTrue(Path(done['checkpoint_written']).is_file())
            self.assertIn('PASS: pytest -q', Path(done['checkpoint_written']).read_text())

    def test_failure_blocks_and_does_not_consume_next_or_retry(self):
        first = self.store.submit(self.repo, 'First task')
        second = self.store.submit(self.repo, 'Next independent task')
        calls = []

        def failed(task, resume_id):
            calls.append(task['id'])
            return {'exit_code': 75, 'session_id': 's', 'text': '', 'error': 'quota exceeded'}

        result = run_queue(self.store, failed, lambda task: self.fail('must not verify'),
                           lambda *args: self.fail('must not checkpoint'), max_tasks=10)
        self.assertEqual(result['completed'], 0)
        self.assertEqual(calls, [first['id']])
        self.assertEqual(self.store.load(first['id'])['status'], 'blocked')
        self.assertEqual(self.store.load(second['id'])['status'], 'queued')
        paused = run_queue(self.store, failed, lambda task: self.fail('must not verify'),
                           lambda *args: self.fail('must not checkpoint'), max_tasks=10)
        self.assertIn('quota pause', paused['stopped'])
        self.assertEqual(calls, [first['id']])
        self.store.acknowledge_quota(first['id'])
        run_queue(self.store, failed, lambda task: self.fail('must not verify'),
                  lambda *args: self.fail('must not checkpoint'), max_tasks=10)
        self.assertEqual(calls, [first['id'], second['id']])

    def test_missing_test_evidence_blocks_completion(self):
        task = self.store.submit(self.repo, 'Fix a bug')
        def execute(item, resume_id):
            (self.repo / 'changed.txt').write_text('change')
            return {'exit_code': 0, 'session_id': 's',
                    'text': json.dumps({'status': 'complete', 'decisions': 'fixed', 'remaining': 'none'})}
        result = run_queue(self.store, execute, lambda item: {'ok': False, 'summary': 'no test recipe'},
                           lambda *args: self.fail('no checkpoint on failed verification'))
        self.assertEqual(result['completed'], 0)
        self.assertEqual(self.store.load(task['id'])['status'], 'blocked')

    def test_external_executor_uses_native_oneshot_protocol_without_api(self):
        task = self.store.submit(self.repo, 'Implement parsing')
        fake = self.root / 'fake-hermes'
        argv_log = self.root / 'argv.json'
        fake.write_text('#!/usr/bin/env python3\nimport json,sys\n'
                        f'open({str(argv_log)!r}, "w").write(json.dumps(sys.argv[1:]))\n'
                        'print(json.dumps({"type":"result","session_id":"local-session",'
                        '"exit_code":0,"text":json.dumps({"status":"complete",'
                        '"decisions":"done","remaining":"none"})}))\n')
        fake.chmod(0o700)
        result = execute_task(task, None, hermes=str(fake), timeout=10)
        self.assertEqual(result['session_id'], 'local-session')
        self.assertIn('"status": "complete"', result['text'])
        args = json.loads(argv_log.read_text())
        self.assertIn('--oneshot', args)
        self.assertIn('--query-file', args)
        self.assertNotIn('--resume', args)
        self.assertNotIn('--continue', args)
        related = self.store.submit(self.repo, 'Add more parsing tests', related=task['id'])
        execute_task(related, 'local-session', hermes=str(fake), timeout=10)
        args = json.loads(argv_log.read_text())
        self.assertEqual(args[args.index('--resume') + 1], 'local-session')
        self.assertIn('Read the task brief', (self.store.root / task['id'] / 'prompt.txt').read_text())
        self.assertIn('Do not deploy or restart production services',
                      (self.store.root / task['id'] / 'prompt.txt').read_text())
        self.assertNotIn('Implement parsing', (self.store.root / task['id'] / 'prompt.txt').read_text())

    def test_git_fingerprint_detects_a_change_in_an_existing_dirty_file(self):
        path = self.repo / 'a.txt'
        path.write_text('before')
        before = git_fingerprint(self.repo)
        path.write_text('after')
        self.assertNotEqual(before, git_fingerprint(self.repo))
    def test_installed_hermes_verify_runs_test_phase_only_offline(self):
        manifest_dir = self.repo / '.hermes'
        manifest_dir.mkdir()
        (manifest_dir / 'environment.json').write_text(json.dumps({
            'name': 'offline-fixture', 'kind': 'python',
            'test': ['python3 -c "print(123)"'], 'start': 'exit 42'}))
        outcome = verify_task({'repo': str(self.repo)})
        self.assertTrue(outcome['ok'], outcome)
        self.assertIn('python3 -c', outcome['summary'])

    def test_installed_hermes_verify_rejects_empty_recipe(self):
        manifest_dir = self.repo / '.hermes'
        manifest_dir.mkdir()
        (manifest_dir / 'environment.json').write_text(json.dumps({
            'name': 'offline-fixture', 'kind': 'python', 'test': []}))
        outcome = verify_task({'repo': str(self.repo)})
        self.assertFalse(outcome['ok'])
        self.assertIn('no test commands', outcome['summary'])
    def test_quota_failure_is_recorded_without_retrying(self):
        task = self.store.submit(self.repo, 'Do one task')
        calls = []
        def fail(item, resume_id):
            calls.append(item['id'])
            return {'exit_code': 1, 'session_id': 's', 'text': '', 'error': 'HTTP 429 quota exceeded'}
        run_queue(self.store, fail, lambda item: self.fail('should not verify'),
                  lambda *args: self.fail('should not checkpoint'))
        state = self.store.load(task['id'])
        self.assertEqual(calls, [task['id']])
        self.assertEqual(state['failure_code'], 'quota')
        self.assertNotIn('HTTP 429', json.dumps(state))
        second = self.store.submit(self.repo, 'Different task')
        again = run_queue(self.store, fail, lambda item: self.fail('must not verify'),
                          lambda *args: self.fail('must not checkpoint'))
        self.assertIn('quota', again['stopped'])
        self.assertEqual(self.store.load(second['id'])['status'], 'queued')
        self.assertEqual(calls, [task['id']])

    def test_only_selected_checkpoint_path_enters_seed(self):
        from unittest.mock import patch
        handoffs = self.root / 'handoffs'
        handoffs.mkdir()
        selected = handoffs / 'selected.md'
        selected.write_text('Handoff details, not the transcript')
        other = handoffs / 'other.md'
        other.write_text('Unrelated transcript')
        with patch('orchestrator.project_checkpoints', return_value=handoffs), \
             patch('task_session.project_checkpoints', return_value=handoffs):
            task = self.store.submit(self.repo, 'New independent work', checkpoint=selected)
            fake = self.root / 'fake-hermes'
            fake.write_text('#!/usr/bin/env python3\nimport json\n'
                            'print(json.dumps({"type":"result","session_id":"s",'
                            '"exit_code":0,"text":"{}"}))\n')
            fake.chmod(0o700)
            execute_task(task, None, hermes=str(fake), timeout=10)
        seed = (Path(task['brief']).parent / 'prompt.txt').read_text()
        self.assertIn(str(selected), seed)
        self.assertNotIn(str(other), seed)
        self.assertNotIn('Handoff details', seed)
        self.assertNotIn('Unrelated transcript', seed)
    def test_verifier_rechecks_git_diff_after_tests_mutate_tracked_code(self):
        tracked = self.repo / 'src.txt'
        tracked.write_text('clean\n')
        subprocess.run(['git', '-C', str(self.repo), 'add', 'src.txt'], check=True)
        subprocess.run(['git', '-C', str(self.repo), '-c', 'user.name=Test',
                        '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'src'], check=True)
        (self.repo / 'mutate.py').write_text('from pathlib import Path\nPath("src.txt").write_text("bad  \\n")\n')
        manifest = self.repo / '.hermes'
        manifest.mkdir()
        (manifest / 'environment.json').write_text(json.dumps({
            'name': 'mutation-fixture', 'kind': 'python', 'test': ['python3 mutate.py']}))
        outcome = verify_task({'repo': str(self.repo)})
        self.assertFalse(outcome['ok'])
        self.assertIn('git diff', outcome['summary'])
    def test_shutdown_terminates_synthetic_worker_and_leaves_task_unreplayed(self):
        import threading
        from orchestrator import ShutdownRequested
        task = self.store.submit(self.repo, 'No real model call')
        pid_file = self.root / 'worker.pid'
        fake = self.root / 'synthetic-worker'
        fake.write_text('#!/usr/bin/env python3\nimport os,time\n'
                        f'open({str(pid_file)!r}, "w").write(str(os.getpid()))\n'
                        'time.sleep(60)\n')
        fake.chmod(0o700)
        stop = threading.Event()
        timer = threading.Timer(1, stop.set)
        timer.start()
        try:
            with self.assertRaises(ShutdownRequested):
                execute_task(task, None, hermes=str(fake), timeout=10, shutdown=stop)
            self.assertTrue(pid_file.exists())
            with self.assertRaises(ProcessLookupError):
                os.kill(int(pid_file.read_text()), 0)
        finally:
            timer.join()
    def test_supervisor_sigterm_stops_fake_worker_and_preserves_running_state(self):
        import signal
        import time
        task = self.store.submit(self.repo, 'Synthetic task only')
        fake_bin = self.root / 'bin'
        fake_bin.mkdir()
        pid_file = self.root / 'agent.pid'
        fake = fake_bin / 'hermes'
        fake.write_text('#!/usr/bin/env python3\nimport os,time\n'
                        f'open({str(pid_file)!r}, "w").write(str(os.getpid()))\n'
                        'time.sleep(60)\n')
        fake.chmod(0o700)
        env = dict(os.environ, PATH=str(fake_bin) + ':' + os.environ['PATH'])
        script = Path(__file__).with_name('orchestrator.py')
        process = subprocess.Popen(['python3', str(script), '--store', str(self.store.root),
                                    'run', '--watch'], env=env,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(50):
                if pid_file.exists():
                    break
                time.sleep(0.1)
            self.assertTrue(pid_file.exists(), 'fake worker did not start')
            process.send_signal(signal.SIGTERM)
            self.assertEqual(process.wait(timeout=12), 0)
            self.assertEqual(self.store.load(task['id'])['status'], 'running')
            with self.assertRaises(ProcessLookupError):
                os.kill(int(pid_file.read_text()), 0)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
            if pid_file.exists():
                try:
                    os.kill(int(pid_file.read_text()), signal.SIGKILL)
                except ProcessLookupError:
                    pass
    def test_shutdown_cancels_nonagent_verification_process(self):
        import threading
        from orchestrator import ShutdownRequested, run_interruptible
        pid_file = self.root / 'verify.pid'
        fake = self.root / 'synthetic-verifier'
        fake.write_text('#!/usr/bin/env python3\nimport os,time\n'
                        f'open({str(pid_file)!r}, "w").write(str(os.getpid()))\n'
                        'time.sleep(60)\n')
        fake.chmod(0o700)
        stop = threading.Event()
        timer = threading.Timer(1, stop.set)
        timer.start()
        try:
            with self.assertRaises(ShutdownRequested):
                run_interruptible([str(fake)], cwd=self.repo, timeout=10, shutdown=stop)
            with self.assertRaises(ProcessLookupError):
                os.kill(int(pid_file.read_text()), 0)
        finally:
            timer.join()


class ServiceManifestTests(unittest.TestCase):
    def test_sidecar_compose_config_is_isolated_and_restartable_offline(self):
        manifest = Path(__file__).with_name('compose.supervisor.yml')
        env = dict(os.environ, HERMES_IMAGE_REF='sha256:' + '0' * 64,
                   HERMES_QUEUE_HOST_PATH='/fixture/queue',
                   HERMES_CHECKPOINT_HOST_PATH='/fixture/checkpoints',
                   HERMES_CODE_HOST_PATH='/fixture/code',
                   HERMES_WORKER_HOME_HOST_PATH='/fixture/worker-home',
                   HERMES_CONFIG_HOST_PATH='/fixture/config.yaml',
                   HERMES_SKILLS_HOST_PATH='/fixture/skills',
                   HERMES_MEMORIES_HOST_PATH='/fixture/memories',
                   HERMES_WORKSPACE_HOST_PATH='/fixture/repo',
                   HERMES_WORKSPACE_PATH='/workspaces/fixture-repo',
                   HERMES_UID='10000', HERMES_GID='10000')
        result = subprocess.run(['docker', 'compose', '--profile', 'execution', '-f', str(manifest), 'config',
                                 '--format', 'json'], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        config = json.loads(result.stdout)
        self.assertEqual(set(config['services']), {'supervisor', 'worker', 'codex-proxy'})
        service = config['services']['supervisor']
        self.assertEqual(service['restart'], 'unless-stopped')
        self.assertEqual(service['user'], '10000:10000')
        self.assertTrue(service['init'])
        self.assertTrue(service['read_only'])
        self.assertFalse(service.get('privileged', False))
        self.assertFalse(service.get('ports'))
        self.assertEqual(service['network_mode'], 'none')
        self.assertEqual(service['cpus'], 0.1)
        self.assertEqual(int(service['mem_limit']), 128 * 1024 * 1024)
        self.assertEqual(service['pids_limit'], 32)
        self.assertEqual(service['entrypoint'], ['/opt/hermes/.venv/bin/python'])
        self.assertIn('monitor', service['command'])
        self.assertEqual({v['target'] for v in service['volumes']},
                         {'/opt/data/autonomous-development', '/opt/data/autonomous-development/tasks'})
        self.assertTrue(all(v['read_only'] for v in service['volumes']))
        self.assertNotIn('HERMES_HOME', service['environment'])
        self.assertNotIn('/worker-home/auth.json', {v['target'] for v in service['volumes']})
        self.assertFalse(service.get('depends_on'))
        worker = config['services']['worker']
        self.assertEqual(worker['networks']['worker_isolated']['ipv4_address'], '172.30.50.2')
        self.assertIn('execution', worker['profiles'])
        self.assertEqual(worker['cpus'], 1.0)
        self.assertEqual(int(worker['mem_limit']), 1536 * 1024 * 1024)
        self.assertEqual(worker['pids_limit'], 128)
        self.assertEqual(worker['command'][-2:], ['--allowed-repo', '/workspaces/fixture-repo'])
        self.assertNotIn('/opt/data', {v['target'] for v in worker['volumes']})
        self.assertNotIn('/var/run/docker.sock', {v['target'] for v in worker['volumes']})
        self.assertNotIn('/worker-home/auth.json', {v['target'] for v in worker['volumes']})
        self.assertEqual(worker['environment']['HERMES_HOME'], '/worker-home')
        self.assertEqual({v['target'] for v in worker['volumes'] if not v.get('read_only', False)},
                         {'/worker-home', '/opt/data/autonomous-development/tasks',
                          '/opt/data/development-checkpoints', '/workspaces/fixture-repo'})
        self.assertTrue(all(v['bind']['create_host_path'] is False for s in config['services'].values()
                            for v in s['volumes']))
        self.assertTrue(all(s['logging']['options'] == {'max-size': '5m', 'max-file': '2'}
                            for s in config['services'].values()))

    def test_uninspected_image_mount_and_uid_cannot_pass_compose_preflight(self):
        manifest = Path(__file__).with_name('compose.supervisor.yml')
        env = {k: v for k, v in os.environ.items()
               if not k.startswith('HERMES_')}
        result = subprocess.run(['docker', 'compose', '-f', str(manifest), 'config', '-q'],
                                env=env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('HERMES_IMAGE_REF', result.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
