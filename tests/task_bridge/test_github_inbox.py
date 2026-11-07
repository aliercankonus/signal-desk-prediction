"""Provider-free issue #45 inbox and recovery regressions."""
import base64
import hashlib
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace

WORKER = Path(__file__).resolve().parents[2] / 'autonomous-development'
sys.path.insert(0, str(WORKER))
from github_inbox import Inbox, GitHub, REPO, RateLimited, canonical, verify_grant, openssl_verify
from signal_desk.task_bridge.adapters import HermesAgent
from signal_desk.task_bridge.bridge import Policy
from signal_desk.task_bridge.context import ExecutionContext
from signal_desk.task_bridge.recovery import checkpoint

ROOT = Path(__file__).resolve().parents[2]


class FakeGitHub:
    def __init__(self):
        self.feed = {41: [], 45: []}
        self.targets = {}
        self.posts = []
        self.fail_publish = False

    def latest(self, issue):
        return max((row['id'] for row in self.feed[issue]), default=50)

    def comments(self, issue, since, etag=None):
        for row in self.feed[issue]:
            yield row, 'etag'

    def comment(self, issue, number):
        return self.targets[(issue, number)]

    def publish(self, issue, text):
        if self.fail_publish:
            raise RuntimeError('ambiguous POST')
        self.posts.append((issue, json.loads(text)))
        return len(self.posts)


def comment(number, body, *, edited=False):
    return {'id': number, 'body': body, 'created_at': '2026-11-08T00:00:00Z',
            'updated_at': '2026-11-08T00:00:01Z' if edited else '2026-11-08T00:00:00Z'}


class TransportTests(unittest.TestCase):
    def test_latest_cursor_and_paginated_feed_bounded_without_network(self):
        client = GitHub.__new__(GitHub)
        seen = []
        def fake_request(method, path, body=None, etag=None):
            seen.append((method, path, etag))
            if path.endswith('/issues/41'):
                return {'number': 41, 'comments': 101}, None
            if 'page=2' in path and 'since=' not in path:
                return [comment(1001, 'last')], 'last-etag'
            if '&page=1&' in path:
                return [comment(i, 'ordinary') for i in range(1, 101)], 'first-etag'
            return [comment(101, 'ordinary')], None
        client.request = fake_request
        self.assertEqual(client.latest(41), 1001)
        rows = list(client.comments(41, '2026-11-07T00:00:00Z'))
        self.assertEqual(len(rows), 101)
        self.assertEqual(seen[-1][2], None)
        with self.assertRaisesRegex(ValueError, 'outside enrollment'):
            list(client.comments(99, '2026-11-07T00:00:00Z'))


class InboxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path.home())
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / 'github-inbox'
        self.root.mkdir(mode=0o700)
        (self.root / 'inbox.lock').touch(mode=0o600)
        self.enrollment = self.base / 'enrollment.json'
        self.enrollment.write_text('private')
        self.enrollment.chmod(0o600)
        self.config = {'runner_commit': 'a' * 40, 'interval_seconds': 300}
        self.policy = SimpleNamespace(issue=43, identity='b' * 64)
        self.github = FakeGitHub()
        self.calls = []
        self.inbox = Inbox(self.enrollment, self.root, self.github, self.execute,
                           verifier=lambda key, message, signature: signature == b'x' * 64)
        self.inbox._config = lambda: (self.config, self.policy, b'public')
        self.inbox._save({'v': 1, 'enabled': True, 'start': '2026-11-07T00:00:00Z',
            'start_cursor': {'41': 50, '45': 50}, 'cursor': {'41': 50, '45': 50},
            'etag': {}, 'claim': None, 'next_poll': 0,
            'enrollment_sha256': hashlib.sha256(b'private').hexdigest()})

    def execute(self, config, policy):
        # The claim must precede the first possible external execution effect.
        assert self.inbox._read()['claim']['status'] == 'claimed'
        self.calls.append((config, policy))
        return {'status': 'review-ready', 'id': 'c' * 32, 'ci': 'pending'}

    def grant(self, issue=41, instruction_id=51, grant_id=52, text=None):
        text = text or ('RUN FROZEN DEVELOPMENT TASK #43 AUTH ' + self.policy.identity)
        target = comment(instruction_id, text)
        self.github.targets[(issue, instruction_id)] = target
        payload = {'v': 1, 'repo': REPO, 'issue': issue,
                   'instruction_id': instruction_id,
                   'instruction_sha256': hashlib.sha256(text.encode()).hexdigest(),
                   'task_issue': 43, 'authority_identity': self.policy.identity,
                   'runner_commit': self.config['runner_commit'], 'scope': 'development-only'}
        envelope = {'signal_desk_grant_v1': {'payload': payload,
                    'signature': base64.b64encode(b'x' * 64).decode()}}
        self.github.feed[issue] = [target, comment(grant_id, json.dumps(envelope))]
        return payload

    def test_enroll_snapshots_backlog_disabled_and_refuses_reset(self):
        self.github.feed[41] = [comment(65, 'historical blocked smoke')]
        fresh = Inbox(self.enrollment, self.base / 'fresh-inbox', self.github, self.execute)
        fresh._config = self.inbox._config
        fresh.enroll('2026-11-08T00:00:00Z')
        state = fresh.doctor()
        self.assertFalse(state['enabled'])
        self.assertEqual(state['cursor'], {'41': 65, '45': 50})
        self.assertEqual(fresh.tick()['status'], 'disabled')
        with self.assertRaises(FileExistsError):
            fresh.enroll('2026-11-08T00:00:01Z')
        self.assertFalse(self.calls)

    def test_doctor_disable_and_claim_preservation_are_inert(self):
        self.assertIsNone(self.inbox.doctor()['claim'])
        self.inbox.disable()
        self.assertEqual(self.inbox.tick()['status'], 'disabled')
        self.assertEqual(self.calls, [])
        self.assertFalse(self.inbox.doctor()['enabled'])
        self.assertEqual(self.inbox._read()['cursor'], {'41': 50, '45': 50})

    def test_no_update_no_model_and_cursor(self):
        self.github.feed[41] = [comment(51, 'ordinary status')]
        self.assertEqual(self.inbox.tick()['status'], 'empty')
        self.assertEqual(self.inbox._read()['cursor']['41'], 51)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.github.posts, [])

    def test_eligible_once_restart_no_repeat(self):
        self.grant()
        result = self.inbox.tick()
        self.assertEqual(result['status'], 'review-ready')
        self.assertEqual(len(self.calls), 1)
        self.assertEqual([p[1]['status'] for p in self.github.posts],
                         ['ack', 'running', 'review-ready'])
        self.assertEqual(self.inbox.tick()['status'], 'blocked')
        restarted = Inbox(self.enrollment, self.root, self.github, self.execute)
        restarted._config = self.inbox._config
        self.assertEqual(restarted.tick()['status'], 'blocked')
        self.assertEqual(len(self.calls), 1)

    def test_false_auth_edits_backlog_and_scope_do_not_dispatch(self):
        for case in ('unsigned', 'edited-grant', 'edited-instruction', 'old-target',
                     'wrong-issue', 'wrong-scope', 'wrong-signer'):
            with self.subTest(case=case):
                self.setUp()
                payload = self.grant()
                if case == 'unsigned':
                    self.github.feed[41][1]['body'] = 'GO (not an authenticated grant)'
                elif case == 'edited-grant':
                    self.github.feed[41][1]['updated_at'] = '2026-11-08T00:00:01Z'
                elif case == 'edited-instruction':
                    self.github.targets[(41, 51)]['body'] = 'changed'
                elif case == 'old-target':
                    self.github.targets[(41, 51)]['id'] = 49
                    payload['instruction_id'] = 49
                elif case == 'wrong-issue':
                    payload['issue'] = 45
                elif case == 'wrong-scope':
                    payload['scope'] = 'root-host'
                elif case == 'wrong-signer':
                    self.github.feed[41][1]['body'] = self.github.feed[41][1]['body'].replace(
                        base64.b64encode(b'x' * 64).decode(), base64.b64encode(b'y' * 64).decode())
                if case in ('old-target', 'wrong-issue', 'wrong-scope'):
                    self.github.feed[41][1]['body'] = json.dumps({'signal_desk_grant_v1': {
                        'payload': payload, 'signature': base64.b64encode(b'x' * 64).decode()}})
                if case == 'edited-instruction':
                    self.assertEqual(self.inbox.tick()['status'], 'blocked')
                    self.assertEqual(self.inbox._read()['claim']['reason'],
                                     'signed instruction changed or outside frozen scope')
                else:
                    self.assertEqual(self.inbox.tick()['status'], 'empty')
                self.assertFalse(self.calls)

    def test_crash_quota_and_ambiguous_receipt_preserve_claim(self):
        for outcome in ('crash', 'quota', 'ambiguous-post'):
            with self.subTest(outcome=outcome):
                self.setUp()
                self.grant()
                if outcome == 'ambiguous-post':
                    self.github.fail_publish = True
                else:
                    def fail(config, policy):
                        self.calls.append('invoked')
                        raise RuntimeError(outcome)
                    self.inbox.executor = fail
                self.assertEqual(self.inbox.tick()['status'], 'blocked')
                self.assertEqual(self.inbox._read()['claim']['status'], 'blocked')
                self.assertEqual(self.inbox.tick()['status'], 'blocked')
                self.assertLessEqual(len(self.calls), 1)
                if outcome != 'ambiguous-post':
                    self.assertEqual([p[1]['status'] for p in self.github.posts],
                                     ['ack', 'running', 'blocked'])

    def test_rate_limit_honors_delay_and_does_not_launch(self):
        self.github.comments = lambda *a: (_ for _ in ()).throw(RateLimited(800))
        self.assertEqual(self.inbox.tick()['status'], 'rate-limited')
        self.assertGreater(self.inbox._read()['next_poll'], time.time() + 700)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.inbox.tick()['status'], 'waiting')

    def test_lock_contention(self):
        fd = self.inbox._locked()
        try:
            with self.assertRaises(BlockingIOError):
                self.inbox.tick()
        finally:
            os.close(fd)

    def test_real_ed25519_verifier(self):
        if shutil.which('openssl') is None:
            self.skipTest('collector image lacks OpenSSL CLI; operator must preflight verifier')
        private = self.base / 'signer.pem'
        public = self.base / 'verifier.pem'
        payload = b'bounded grant'
        signed = self.base / 'payload'
        signature = self.base / 'signature'
        signed.write_bytes(payload)
        subprocess.run(['openssl', 'genpkey', '-algorithm', 'Ed25519', '-out', str(private)],
                       check=True, capture_output=True)
        subprocess.run(['openssl', 'pkey', '-in', str(private), '-pubout', '-out', str(public)],
                       check=True, capture_output=True)
        subprocess.run(['openssl', 'pkeyutl', '-sign', '-inkey', str(private), '-rawin',
                        '-in', str(signed), '-out', str(signature)], check=True, capture_output=True)
        self.assertTrue(openssl_verify(public.read_bytes(), payload, signature.read_bytes()))
        self.assertFalse(openssl_verify(public.read_bytes(), payload + b'!', signature.read_bytes()))


class RecoveryDeliveryTests(unittest.TestCase):
    def test_private_checkpoint_intent_and_identity_fence(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            state = Path(directory)
            state.chmod(0o700)
            identity = {'task_issue': 43, 'authorization_identity': 'a' * 64,
                        'runner_commit': 'b' * 40, 'base': 'c' * 40,
                        'branch': 'test-review-note', 'run_id': 'd' * 32,
                        'worktree': str(state / 'worktrees' / ('d' * 32))}
            first = checkpoint(state, identity, 'pre-push', head='e' * 40)
            self.assertEqual(first['last_confirmed'], 'worktree-created')
            saved = json.loads((state / 'recovery-checkpoint.json').read_bytes())
            self.assertEqual(saved['stage'], 'pre-push')
            self.assertEqual((state / 'recovery-checkpoint.json').stat().st_mode & 0o777, 0o600)
            second = checkpoint(state, identity, 'post-push', head='e' * 40)
            self.assertEqual(second['last_confirmed'], 'post-push')
            self.assertEqual(second['previous_stage'], 'pre-push')
            with self.assertRaisesRegex(ValueError, 'identity changed'):
                checkpoint(state, {**identity, 'task_issue': 44}, 'pre-commit')
            self.assertEqual(json.loads((state / 'recovery-checkpoint.json').read_bytes()), second)

    def test_pinned_runbook_injected_before_child_effect(self):
        with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
            root = Path(directory)
            source = root / 'runner'
            source.mkdir()
            subprocess.run(['git', '-C', str(source), 'init', '-q'], check=True)
            subprocess.run(['git', '-C', str(source), 'config', 'user.name', 'Hermes Agent'], check=True)
            subprocess.run(['git', '-C', str(source), 'config', 'user.email',
                            'hermes-agent@users.noreply.github.com'], check=True)
            docs = source / 'docs'
            docs.mkdir()
            recovery = (ROOT / 'docs/HERMES_SESSION_RECOVERY.md').read_bytes()
            (docs / 'HERMES_SESSION_RECOVERY.md').write_bytes(recovery)
            subprocess.run(['git', '-C', str(source), 'add', 'docs/HERMES_SESSION_RECOVERY.md'], check=True)
            subprocess.run(['git', '-C', str(source), 'commit', '-qm', 'fixture'], check=True)
            base = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
            state = root / 'state'
            state.mkdir(mode=0o700)
            worktree = state / 'worktrees' / ('d' * 32)
            policy = Policy(REPO, 43, 'c' * 64, base, 'test-review-note')
            agent = HermesAgent(source, state, policy,
                                help_runner=lambda: ' '.join(HermesAgent.FLAGS))
            agent._approved_context = ExecutionContext('/approved/bin/python', 'a' * 64,
                                                        base, '3.14.9', '8.3.3')
            agent.preflight = lambda: True
            def stop_before_model(argv):
                prompt = (state / 'prompt').read_text()
                self.assertIn(recovery.decode(), prompt)
                self.assertIn('Before/after tests, commit and push', prompt)
                self.assertIn('Private checkpoint:', prompt)
                self.assertIn('Read and follow the full pinned contract below BEFORE editing.', prompt)
                raise RuntimeError('inert boundary')
            agent.execute = stop_before_model
            with self.assertRaisesRegex(RuntimeError, 'inert boundary'):
                agent.run('approved frozen task', worktree)
            self.assertTrue((state / 'prompt').exists())
            saved = json.loads((state / 'recovery-checkpoint.json').read_text())
            self.assertEqual(saved['stage'], 'child-intent')
            self.assertEqual(saved['identity']['run_id'], 'd' * 32)


if __name__ == '__main__':
    unittest.main()
