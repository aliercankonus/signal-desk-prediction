import hashlib
import io
import json
import os
import sqlite3
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch
from pathlib import Path

from signal_desk.task_bridge.bridge import Bridge, Policy, doctor, load_authorization, draft_title, draft_body
from dataclasses import asdict

BODY = (Path(__file__).parent / 'issue22.txt').read_text()
DIGEST = hashlib.sha256(BODY.encode()).hexdigest()
BASE = 'a930a3c715635341e62538a3cc15a260162f6be9'
HEAD = 'f' * 40
SYNTH_POLICY = Policy('aliercankonus/signal-desk-prediction', 101, DIGEST, BASE, 'review-task-101')


class FakeGitHub:
    def __init__(self):
        self.policy = SYNTH_POLICY
        self.repo = 'aliercankonus/signal-desk-prediction'
        self.number = 101
        self.body = BODY
        self.state = 'open'
        self.issue_calls = 0
        self.edit_on_second_issue_read = False
        self.posts = []
        self.fail_post = set()
        self.create_calls = []
        self.pr = {'url': 'https://github.com/aliercankonus/signal-desk-prediction/pull/42',
                   'number': 42, 'title': 'Task bridge draft for issue #101',
                   'draft': True, 'head': HEAD,
                   'body': 'Refs #101\n\nReviewed task branch: `review-task-101`.\n',
                   'pinned_start': BASE, 'target_tip': BASE, 'target_branch': 'main',
                   'target_repo': self.repo, 'ci': 'success', 'ci_head': HEAD}

    def issue(self, repo, number):
        self.issue_calls += 1
        body = 'edited after initial authorization' if (self.edit_on_second_issue_read and
                                                        self.issue_calls >= 2) else self.body
        return {'repo': self.repo, 'number': self.number, 'body': body, 'state': self.state}

    def draft_pr(self, repo, branch):
        return self.pr

    def task_draft(self, repo, branch, head):
        return self.pr

    def create_task_draft(self, repo, branch, head):
        self.create_calls.append((repo, branch, head))
        self.pr = {'url': 'https://github.com/aliercankonus/signal-desk-prediction/pull/42',
                   'number': 42, 'title': 'Task bridge draft for issue #101',
                   'draft': True, 'head': head,
                   'body': 'Refs #101\n\nReviewed task branch: `review-task-101`.\n',
                   'pinned_start': BASE, 'target_tip': BASE, 'target_branch': 'main',
                   'target_repo': self.repo, 'ci': 'pending', 'ci_head': head}
        return 42

    def publish(self, repo, number, text):
        if json.loads(text)['status'] in self.fail_post:
            raise RuntimeError('publication unavailable')
        self.posts.append(text)
        return len(self.posts)

    def statuses(self, repo, number, run_id, expected):
        return [{'id': index, 'status': json.loads(text)['status']}
                for index, text in enumerate(self.posts, 1)
                if json.loads(text).get('run_id') == run_id and
                text == expected.get(json.loads(text)['status'])]


class FakeAgent:
    def __init__(self):
        self.policy = SYNTH_POLICY
        self.calls = 0
        self.action = None
        self.preflight_error = False

    def preflight(self):
        if self.preflight_error:
            raise ValueError('source unavailable')

    def run(self, prompt, worktree):
        self.calls += 1
        if self.action:
            self.action()
        return {'head': HEAD, 'branch': 'review-task-101'}


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name) / 'private'
        self.github = FakeGitHub()
        self.agent = FakeAgent()
        self.policy = Policy('aliercankonus/signal-desk-prediction', 101, DIGEST, BASE, 'review-task-101')
        self.auth_path = Path(self.tmp.name) / 'auth.json'
        self.auth_path.write_text(json.dumps(asdict(self.policy)))
        self.auth_path.chmod(0o600)

    def bridge(self, policy=None):
        return Bridge(self.state, policy or self.policy, self.github, self.agent, auth_path=self.auth_path)

    def test_supervisor_creates_one_controlled_draft_after_child_success_without_gh(self):
        self.github.pr = None
        seen = []
        original = self.agent.run
        def capture(prompt, worktree):
            seen.append(prompt)
            return original(prompt, worktree)
        self.agent.run = capture
        result = self.bridge().once()
        self.assertEqual(result['status'], 'review-ready')
        self.assertEqual(result['ci'], 'pending')
        self.assertEqual(self.github.create_calls, [(self.policy.repo, self.policy.branch, HEAD)])
        self.assertIn('Do not require gh or create the task PR', seen[0])
        self.assertLess(seen[0].index('Do not require gh'), seen[0].index(BODY))
        with sqlite3.connect(self.state / 'journal.sqlite3') as db:
            self.assertEqual(db.execute('SELECT stage,expected_head,number,url FROM pr_creations').fetchone(),
                             ('verified', HEAD, 42, self.github.pr['url']))
        self.assertEqual(self.bridge().once()['status'], 'review-ready')
        self.assertEqual(len(self.github.create_calls), 1)

    def test_matching_existing_draft_is_reused_without_any_post(self):
        result = self.bridge().once()
        self.assertEqual(result['status'], 'review-ready')
        self.assertEqual(self.github.create_calls, [])
        with sqlite3.connect(self.state / 'journal.sqlite3') as db:
            self.assertEqual(db.execute('SELECT stage,expected_head,number FROM pr_creations').fetchone(),
                             ('reused', HEAD, 42))

    def test_conflicting_existing_draft_never_triggers_a_second_pr(self):
        for key, value in (('head', 'e'*40), ('draft', False), ('body', 'Refs #101\nissue prose'),
                           ('title', 'issue supplied title'), ('target_repo', 'elsewhere/repo'),
                           ('number', 43)):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as directory:
                gh, agent = FakeGitHub(), FakeAgent()
                gh.pr[key] = value
                bridge = Bridge(Path(directory) / 'state', self.policy, gh, agent, auth_path=self.auth_path)
                self.assertEqual(bridge.once()['status'], 'blocked')
                self.assertEqual(gh.create_calls, [])
                self.assertEqual(doctor(bridge.state, self.policy)['status'], 'blocked')

    def test_edited_issue_after_child_stops_before_pr_post(self):
        self.github.pr = None
        self.agent.action = lambda: setattr(self.github, 'body', 'edited after child')
        self.assertEqual(self.bridge().once()['status'], 'blocked')
        self.assertEqual(self.github.create_calls, [])
        self.assertIsNone(self.bridge()._pr_creation())

    def test_issue_changed_during_post_cannot_be_reported_review_ready(self):
        self.github.pr = None
        original = self.github.create_task_draft
        def change_after_post(repo, branch, head):
            number = original(repo, branch, head)
            self.github.body = 'edited while draft POST was in flight'
            return number
        self.github.create_task_draft = change_after_post
        self.assertEqual(self.bridge().once()['status'], 'blocked')
        self.assertEqual(self.bridge()._pr_creation()['stage'], 'responded')
        self.assertEqual(len(self.github.create_calls), 1)
        self.assertEqual(self.bridge().once()['status'], 'blocked')

    def test_ambiguous_post_stays_blocked_with_durable_intent_and_no_retry(self):
        self.github.pr = None
        original = self.github.create_task_draft
        def ambiguous(repo, branch, head):
            self.assertEqual(self.bridge()._pr_creation()['stage'], 'intent')
            original(repo, branch, head)
            raise TimeoutError('response lost after external effect')
        self.github.create_task_draft = ambiguous
        result = self.bridge().once()
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(self.bridge()._pr_creation(),
                         {'stage': 'intent', 'expected_head': HEAD, 'number': None, 'url': None})
        self.assertEqual(doctor(self.state, self.policy)['status'], 'blocked')
        self.assertEqual(doctor(self.state, self.policy)['pr_creation']['stage'], 'intent')
        before = (self.state / 'journal.sqlite3').read_bytes()
        observation = self.bridge().reconcile()
        self.assertEqual(observation['pr_creation']['stage'], 'intent')
        self.assertIn('draft result not journaled', observation['result_mismatch'])
        self.assertEqual((self.state / 'journal.sqlite3').read_bytes(), before)
        self.assertEqual(self.bridge().once()['status'], 'blocked')
        self.assertEqual(len(self.github.create_calls), 1)

    def test_crash_after_post_response_preserves_stage_without_repost(self):
        for method, expected in (('_pr_response', 'intent'), ('_pr_verified', 'responded')):
            with self.subTest(method=method), tempfile.TemporaryDirectory() as directory:
                gh, agent = FakeGitHub(), FakeAgent()
                gh.pr = None
                bridge = Bridge(Path(directory) / 'state', self.policy, gh, agent, auth_path=self.auth_path)
                with patch.object(bridge, method, side_effect=KeyboardInterrupt):
                    self.assertEqual(bridge.once()['status'], 'blocked')
                self.assertEqual(bridge._pr_creation()['stage'], expected)
                self.assertEqual(bridge.once()['status'], 'blocked')
                self.assertEqual(len(gh.create_calls), 1)

    def test_pr_readback_mismatch_or_bad_response_cannot_become_ready(self):
        for failure in ('bad_response', 'wrong_number'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                gh, agent = FakeGitHub(), FakeAgent()
                gh.pr = None
                original = gh.create_task_draft
                def create(repo, branch, head):
                    original(repo, branch, head)
                    if failure == 'wrong_number':
                        gh.pr['number'] = 43
                        return 42
                    return None
                gh.create_task_draft = create
                bridge = Bridge(Path(directory) / 'state', self.policy, gh, agent, auth_path=self.auth_path)
                self.assertEqual(bridge.once()['status'], 'blocked')
                self.assertEqual(bridge._pr_creation()['stage'],
                                 'responded' if failure == 'wrong_number' else 'intent')
                self.assertEqual(doctor(bridge.state, self.policy)['status'], 'blocked')
                self.assertEqual(len(gh.create_calls), 1)
                self.assertEqual(bridge.once()['status'], 'blocked')
                self.assertEqual(len(gh.create_calls), 1)

    def test_verified_draft_with_failed_status_post_remains_blocked_without_retry(self):
        self.github.pr = None
        self.github.fail_post = {'review-ready'}
        row = self.bridge().once()
        self.assertEqual(row['status'], 'blocked')
        self.assertEqual(row['head'], HEAD)
        self.assertEqual(self.bridge()._pr_creation()['stage'], 'verified')
        self.assertFalse(self.bridge().reconcile()['publication_consistent'])
        self.assertEqual(self.bridge().once()['status'], 'blocked')
        self.assertEqual(len(self.github.create_calls), 1)

    def test_duplicate_ready_rejects_missing_or_tampered_pr_receipt(self):
        for field, value in (('stage', 'intent'), ('stage', 'responded'), ('number', 43)):
            with self.subTest(field=field, value=value), tempfile.TemporaryDirectory() as directory:
                gh, agent = FakeGitHub(), FakeAgent()
                bridge = Bridge(Path(directory) / 'state', self.policy, gh, agent, auth_path=self.auth_path)
                self.assertEqual(bridge.once()['status'], 'review-ready')
                with sqlite3.connect(bridge.state / 'journal.sqlite3') as db:
                    if field == 'stage':
                        db.execute('UPDATE pr_creations SET stage=?', (value,))
                    else:
                        db.execute('UPDATE pr_creations SET number=?', (value,))
                self.assertEqual(doctor(bridge.state, self.policy)['status'], 'blocked')
                self.assertEqual(bridge.once()['status'], 'blocked')
                self.assertEqual(bridge.status()['status'], 'blocked')
                self.assertEqual(gh.create_calls, [])

    def test_reconcile_reports_corrupt_pr_creation_schema_without_crashing(self):
        ready = self.bridge().once()
        assert ready is not None
        self.assertEqual(ready['status'], 'review-ready')
        with sqlite3.connect(self.state / 'journal.sqlite3') as db:
            db.execute('DROP TABLE pr_creations')
            db.execute('CREATE TABLE pr_creations (id INTEGER PRIMARY KEY)')
        self.assertEqual(doctor(self.state, self.policy)['status'], 'blocked')
        result = self.bridge().reconcile()
        self.assertEqual(result['status'], 'blocked')
        self.assertTrue(result['pr_creation_inspection_unavailable'])
        self.assertIn('PR publication receipt missing or invalid', result['result_mismatch'])

    def test_reconcile_reports_multiple_pr_receipts_without_crashing(self):
        ready = self.bridge().once()
        assert ready is not None
        self.assertEqual(ready['status'], 'review-ready')
        with sqlite3.connect(self.state / 'journal.sqlite3') as db:
            db.execute('DROP TABLE pr_creations')
            db.execute('CREATE TABLE pr_creations (id INTEGER PRIMARY KEY, stage TEXT, expected_head TEXT, number INTEGER, url TEXT)')
            for id_ in (1, 2):
                db.execute('INSERT INTO pr_creations VALUES (?,?,?,?,?)',
                           (id_, 'reused', HEAD, 42, self.github.pr['url']))
        self.assertEqual(doctor(self.state, self.policy)['status'], 'blocked')
        result = self.bridge().reconcile()
        self.assertEqual(result['status'], 'blocked')
        self.assertTrue(result['pr_creation_inspection_unavailable'])
        self.assertIn('PR publication receipt missing or invalid', result['result_mismatch'])

    def test_wrong_id_pr_receipt_never_verifies_review_ready(self):
        ready = self.bridge().once()
        assert ready is not None
        self.assertEqual(ready['status'], 'review-ready')
        with sqlite3.connect(self.state / 'journal.sqlite3') as db:
            db.execute('DROP TABLE pr_creations')
            db.execute('CREATE TABLE pr_creations (id INTEGER PRIMARY KEY, stage TEXT, expected_head TEXT, number INTEGER, url TEXT)')
            db.execute('INSERT INTO pr_creations VALUES (?,?,?,?,?)',
                       (2, 'reused', HEAD, 42, self.github.pr['url']))
        self.assertEqual(doctor(self.state, self.policy)['status'], 'blocked')
        result = self.bridge().reconcile()
        self.assertEqual(result['status'], 'blocked')
        self.assertTrue(result['pr_creation_inspection_unavailable'])
        duplicate = self.bridge().once()
        assert duplicate is not None
        self.assertEqual(duplicate['status'], 'blocked')

    def test_changed_authority_during_draft_discovery_prevents_create_post(self):
        for mutation in ('issue', 'authorization'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                gh, agent = FakeGitHub(), FakeAgent()
                gh.pr = None  # type: ignore[assignment]
                self.auth_path.write_text(json.dumps(asdict(self.policy)))
                self.auth_path.chmod(0o600)
                def discover(repo, branch, head):
                    if mutation == 'issue':
                        gh.state = 'closed'
                    else:
                        self.auth_path.write_text('{}')
                    return None
                gh.task_draft = discover  # type: ignore[assignment]
                bridge = Bridge(Path(directory) / 'state', self.policy, gh, agent, auth_path=self.auth_path)
                result = bridge.once()
                assert result is not None
                self.assertEqual(result['status'], 'blocked')
                self.assertEqual(gh.create_calls, [])
                self.assertEqual(doctor(bridge.state, self.policy)['status'], 'blocked')

    def test_direct_bridge_without_private_record_never_dispatches(self):
        result = Bridge(self.state, self.policy, self.github, self.agent).once()
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(self.agent.calls, 0)
        self.assertEqual(self.github.posts, [])
        self.assertIsNone(self.bridge().status())

    def test_direct_bridge_rejects_authorization_inside_private_state(self):
        self.state.mkdir(mode=0o700)
        inside = self.state / 'auth.json'
        inside.write_text(json.dumps(asdict(self.policy)))
        inside.chmod(0o600)
        result = Bridge(self.state, self.policy, self.github, self.agent, auth_path=inside).once()
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(self.agent.calls, 0)
        self.assertEqual(self.github.posts, [])
        self.assertIsNone(self.bridge().status())

    def test_direct_bridge_rejects_effectful_adapter_policy_mismatch(self):
        different = Policy(self.policy.repo, 102, DIGEST, BASE, 'review-task-102')
        for adapter in (self.agent, self.github):
            with self.subTest(adapter=type(adapter).__name__):
                adapter.policy = different
                result = self.bridge().once()
                self.assertEqual(result['status'], 'blocked')
                self.assertEqual(self.agent.calls, 0)
                self.assertEqual(self.github.posts, [])
                self.assertIsNone(self.bridge().status())
                adapter.policy = self.policy

    def test_direct_bridge_rejects_adapter_without_policy(self):
        del self.agent.policy
        result = self.bridge().once()
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(self.agent.calls, 0)
        self.assertEqual(self.github.posts, [])
        self.assertIsNone(self.bridge().status())

    def test_cli_reconcile_uses_private_authorization_for_remote_readback(self):
        from signal_desk.task_bridge.__main__ import main
        self.assertEqual(self.bridge().once()['status'], 'review-ready')
        output = io.StringIO()
        with patch('signal_desk.task_bridge.__main__.GitHubREST', return_value=self.github), \
             redirect_stdout(output):
            self.assertEqual(main(['reconcile', '--state', str(self.state),
                                   '--auth', str(self.auth_path)]), 0)
        result = json.loads(output.getvalue())
        self.assertTrue(result['publication_consistent'])
        self.assertEqual(result['observed_pr']['head'], HEAD)
        self.assertNotIn('reason', result)

    def test_once_records_before_invocation_and_duplicate_poll_does_not_redispatch(self):
        def inspect():
            row = self.bridge().status()
            self.assertEqual(row['status'], 'running')
            self.assertEqual(row['base'], BASE)
            self.assertEqual(row['body_digest'], DIGEST)
            self.assertEqual(row['branch'], 'review-task-101')
            self.assertTrue(row['worktree'])
        self.agent.action = inspect
        self.assertEqual(self.bridge().once()['status'], 'review-ready')
        self.assertEqual(self.bridge().once()['status'], 'review-ready')
        self.assertEqual(self.agent.calls, 1)
        self.assertEqual([json.loads(m)['status'] for m in self.github.posts],
                         ['queued', 'running', 'review-ready'])
        self.assertIn(HEAD, self.github.posts[-1])

    def test_once_journals_pinned_start_separately_from_advanced_target_tip(self):
        self.github.pr['target_tip'] = 'd' * 40
        result = self.bridge().once()
        self.assertEqual(result['status'], 'review-ready')
        self.assertEqual(result['base'], BASE)
        self.assertEqual(result['target_tip'], 'd' * 40)
        with sqlite3.connect(self.state / 'journal.sqlite3') as db:
            self.assertEqual(db.execute('SELECT base,target_tip FROM runs').fetchone(),
                             (BASE, 'd' * 40))
        payload = json.loads(self.github.posts[-1])
        self.assertEqual(payload['base'], BASE)
        self.assertEqual(payload['target_tip'], 'd' * 40)

    def test_main_advancing_after_review_ready_does_not_block_reconciliation_or_duplicate_once(self):
        self.assertEqual(self.bridge().once()['status'], 'review-ready')
        self.github.pr['target_tip'] = 'e' * 40
        observation = self.bridge().reconcile()
        self.assertEqual(observation['result_mismatch'], [])
        self.assertEqual(observation['target_tip'], BASE)
        self.assertEqual(observation['observed_pr']['target_tip'], 'e' * 40)
        result = self.bridge().once()
        self.assertEqual(result['status'], 'review-ready')
        self.assertEqual(result['target_tip'], 'e' * 40)
        self.assertEqual(doctor(self.state, self.policy)['status'], 'review-ready')
        self.assertEqual(self.agent.calls, 1)

    def test_once_rejects_wrong_target_or_unrelated_pinned_start(self):
        for field, value in (('target_branch', 'develop'), ('target_repo', 'other/repo'),
                             ('pinned_start', '0' * 40)):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                gh, agent = FakeGitHub(), FakeAgent()
                gh.pr[field] = value
                result = Bridge(Path(directory) / 'state', self.policy, gh, agent,
                                auth_path=self.auth_path).once()
                self.assertEqual(result['status'], 'blocked')
                self.assertNotIn('review-ready', [json.loads(text)['status'] for text in gh.posts])

    def test_stored_run_from_other_issue_cannot_report_ready(self):
        self.assertEqual(self.bridge().once()['status'], 'review-ready')
        with sqlite3.connect(self.state / 'journal.sqlite3') as db:
            db.execute('UPDATE runs SET issue_number=23')
        self.assertEqual(doctor(self.state, self.policy)['status'], 'blocked')
        result = self.bridge().once()
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(self.agent.calls, 1)

    def test_duplicate_poll_does_not_report_stale_review_ready_after_pr_disappears(self):
        self.assertEqual(self.bridge().once()['status'], 'review-ready')
        self.github.pr = None
        result = self.bridge().once()
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(self.agent.calls, 1)

    def test_duplicate_poll_blocks_durably_if_issue_is_edited_or_closed(self):
        for change in ('body', 'state'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                gh, agent = FakeGitHub(), FakeAgent()
                bridge = Bridge(Path(directory) / 'state', self.policy, gh, agent,
                                auth_path=self.auth_path)
                self.assertEqual(bridge.once()['status'], 'review-ready')
                before = list(gh.posts)
                setattr(gh, change, 'edited' if change == 'body' else 'closed')
                self.assertEqual(bridge.once()['status'], 'blocked')
                self.assertEqual(bridge.status()['status'], 'blocked')
                self.assertEqual(bridge.once()['status'], 'blocked')
                self.assertEqual(gh.posts, before)
                self.assertEqual(agent.calls, 1)

    def test_duplicate_poll_blocks_if_draft_pr_issue_link_is_removed(self):
        self.assertEqual(self.bridge().once()['status'], 'review-ready')
        self.github.pr['body'] = 'No issue link remains'
        result = self.bridge().once()
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(doctor(self.state, self.policy)['status'], 'blocked')
        self.assertEqual(self.bridge().status()['status'], 'blocked')
        self.assertEqual(self.agent.calls, 1)

    def test_incomplete_journal_blocks_once_doctor_and_reconcile(self):
        self.state.mkdir(mode=0o700)
        sqlite3.connect(self.state / 'journal.sqlite3').close()
        self.assertEqual(self.bridge().once()['status'], 'blocked')
        self.assertEqual(doctor(self.state, self.policy)['status'], 'blocked')
        self.assertEqual(self.bridge().reconcile()['status'], 'blocked')
        self.assertEqual(self.agent.calls, 0)
        self.assertEqual(self.github.posts, [])

    def test_reconcile_reports_mismatched_draft_result_without_promotion(self):
        self.assertEqual(self.bridge().once()['status'], 'review-ready')
        original = self.github.pr['url']
        self.github.pr['body'] = 'No issue link remains'
        self.github.pr['head'] = 'e' * 40
        self.github.pr['ci_head'] = 'e' * 40
        result = self.bridge().reconcile()
        self.assertEqual(result['status'], 'blocked')
        self.assertTrue(result['result_mismatch'])
        self.assertEqual(result['pr_url'], original)
        self.assertEqual(result['head'], HEAD)
        self.assertEqual(self.github.pr['head'], result['observed_pr']['head'])

    def test_simultaneous_worker_cannot_dispatch_twice(self):
        entered, release = threading.Event(), threading.Event()
        self.agent.action = lambda: (entered.set(), release.wait(2))
        worker = threading.Thread(target=self.bridge().once)
        worker.start()
        self.assertTrue(entered.wait(2))
        self.assertEqual(self.bridge().once(), {'status': 'blocked', 'reason': 'worker busy'})
        release.set()
        worker.join(2)
        self.assertEqual(self.agent.calls, 1)

    def test_interrupted_invocation_blocks_restart(self):
        def interrupt():
            raise KeyboardInterrupt()
        self.agent.action = interrupt
        self.assertEqual(self.bridge().once()['status'], 'blocked')
        self.assertEqual(self.bridge().once()['status'], 'blocked')
        self.assertEqual(self.agent.calls, 1)

    def test_restart_running_row_is_ambiguous_and_never_redispatches(self):
        observed = []
        def crash_window():
            observed.append((doctor(self.state, self.policy)['status'], self.bridge().status()['status']))
        self.agent.action = crash_window
        self.bridge().once()
        self.assertEqual(observed, [('blocked', 'running')])
        self.assertEqual(self.agent.calls, 1)

    def test_restart_with_queued_or_running_row_blocks_redispatch(self):
        self.bridge().once()
        for state in ('queued', 'running'):
            with sqlite3.connect(self.state / 'journal.sqlite3') as db:
                db.execute('UPDATE runs SET status=?', (state,))
            row = self.bridge().once()
            self.assertEqual(row['status'], 'blocked')
            self.assertEqual(row['run_id'], self.bridge().status()['run_id'])
            self.assertEqual(self.agent.calls, 1)

    def test_publication_failure_retains_verified_result_without_retry(self):
        self.github.fail_post = {'review-ready'}
        row = self.bridge().once()
        self.assertEqual(row['status'], 'blocked')
        self.assertEqual(row['head'], HEAD)
        self.assertEqual(row['pr_url'], self.github.pr['url'])
        with sqlite3.connect(self.state / 'journal.sqlite3') as db:
            self.assertEqual(list(db.execute('SELECT status,comment_id FROM publications ORDER BY id')),
                             [('queued', 1), ('running', 2), ('review-ready', None), ('blocked', 3)])
        observed = self.bridge().reconcile()
        self.assertEqual([item['status'] for item in observed['observed_publications']],
                         ['queued', 'running', 'blocked'])
        self.assertEqual(observed['publication_receipts'],
                         [{'status': 'queued', 'comment_id': 1},
                          {'status': 'running', 'comment_id': 2},
                          {'status': 'review-ready', 'comment_id': None},
                          {'status': 'blocked', 'comment_id': 3}])
        self.assertFalse(observed['publication_consistent'])
        self.assertEqual(observed['unconfirmed_publications'], ['review-ready'])
        self.github.fail_post = set()
        self.assertEqual(self.bridge().once()['status'], 'blocked')
        self.assertEqual(self.agent.calls, 1)

    def test_queued_publication_failure_blocks_before_invocation(self):
        self.github.fail_post = {'queued'}
        row = self.bridge().once()
        self.assertEqual(row['status'], 'blocked')
        self.assertEqual(self.agent.calls, 0)
        self.assertEqual([json.loads(m)['status'] for m in self.github.posts], ['blocked'])
        self.assertEqual(self.bridge().once()['status'], 'blocked')

    def test_result_only_ready_for_verified_draft_and_exact_head_ci(self):
        self.github.pr['ci_head'] = '0' * 40
        row = self.bridge().once()
        self.assertEqual(row['status'], 'blocked')
        self.assertEqual([json.loads(m)['status'] for m in self.github.posts],
                         ['queued', 'running', 'blocked'])

    def test_untrusted_result_cannot_publish_secret_or_private_path(self):
        self.agent.run = lambda prompt, worktree: {'head': 'secret=/private/token', 'branch': 'review-task-101'}
        self.github.pr['head'] = 'secret=/private/token'
        self.github.pr['ci_head'] = 'secret=/private/token'
        self.assertEqual(self.bridge().once()['status'], 'blocked')
        self.assertEqual([json.loads(m)['status'] for m in self.github.posts],
                         ['queued', 'running', 'blocked'])

    def test_source_preflight_failure_never_publishes_or_invokes(self):
        self.agent.preflight_error = True
        self.assertEqual(self.bridge().once()['status'], 'blocked')
        self.assertIsNone(self.bridge().status())
        self.assertEqual(self.github.posts, [])
        self.assertEqual(self.agent.calls, 0)

    def test_issue_edit_after_progress_but_before_child_blocks_dispatch(self):
        self.github.edit_on_second_issue_read = True
        self.assertEqual(self.bridge().once()['status'], 'blocked')
        self.assertEqual(self.agent.calls, 0)
        self.assertEqual([json.loads(x)['status'] for x in self.github.posts],
                         ['queued', 'running', 'blocked'])

    def test_closed_issue_blocks_new_dispatch(self):
        self.github.state = 'closed'
        self.assertEqual(self.bridge().once()['status'], 'blocked')
        self.assertEqual(self.agent.calls, 0)
        self.assertIsNone(self.bridge().status())

    def test_frozen_issue_task_is_delivered_with_scope_boundaries(self):
        seen = []
        original = self.agent.run
        def capture(prompt, worktree):
            seen.append(prompt)
            return original(prompt, worktree)
        self.agent.run = capture
        self.bridge().once()
        self.assertIn(BODY, seen[0])
        self.assertIn('No deployment', seen[0])

    def test_ambiguous_reconciliation_reads_only_and_requires_operator(self):
        seen = []
        def inspect():
            seen.append(self.bridge().reconcile())
        self.agent.action = inspect
        self.bridge().once()
        self.assertEqual(seen[0]['status'], 'blocked')
        self.assertIsNone(seen[0]['head'])
        self.assertIsNone(seen[0]['target_tip'])
        self.assertEqual(seen[0]['observed_pr']['head'], HEAD)
        self.assertEqual(seen[0]['observed_pr']['target_tip'], BASE)
        self.assertIn('draft result not journaled', seen[0]['result_mismatch'])
        self.assertEqual(seen[0]['operator_review'], True)
        self.assertTrue(seen[0]['publication_consistent'])
        self.assertEqual(len(self.github.posts), 3)

    def test_journal_is_private_and_bounded_to_one_run(self):
        self.bridge().once()
        self.assertEqual((self.state / 'journal.sqlite3').stat().st_mode & 0o777, 0o600)
        with sqlite3.connect(self.state / 'journal.sqlite3') as db:
            self.assertEqual(db.execute('SELECT count(*) FROM runs').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT issue_number FROM runs').fetchone()[0], 101)
            statuses = [row[0] for row in db.execute('SELECT status FROM events ORDER BY id')]
            self.assertEqual(statuses, ['queued', 'running', 'running', 'review-ready'])
            self.assertTrue(all(row[0] for row in db.execute('SELECT recorded_at FROM events')))
            receipts = list(db.execute('SELECT status,comment_id FROM publications ORDER BY id'))
            self.assertEqual(receipts, [('queued', 1), ('running', 2), ('review-ready', 3)])
        self.bridge().once()
        with sqlite3.connect(self.state / 'journal.sqlite3') as db:
            self.assertEqual(db.execute('SELECT count(*) FROM runs').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0], 4)

    def test_unsafe_state_permissions_block_dispatch(self):
        self.state.mkdir(mode=0o755)
        with self.assertRaises(PermissionError):
            self.bridge().once()
        self.assertEqual(self.agent.calls, 0)

    def test_draft_pr_must_link_issue_22(self):
        self.github.pr['body'] = 'unrelated change'
        self.assertEqual(self.bridge().once()['status'], 'blocked')
        self.assertEqual([json.loads(m)['status'] for m in self.github.posts],
                         ['queued', 'running', 'blocked'])

    def test_body_edit_blocks_before_first_dispatch(self):
        self.github.body = 'edited'
        self.assertEqual(self.bridge().once()['status'], 'blocked')
        self.assertEqual(self.agent.calls, 0)
        self.assertIsNone(self.bridge().status())

    def test_policy_cannot_select_other_repo_issue_or_digest(self):
        with self.assertRaises(ValueError):
            Policy('other/repo', 101, DIGEST, BASE, 'review-task-101')
        for policy in (Policy(self.policy.repo, 102, DIGEST, BASE, 'review-task-101'),
                       Policy(self.policy.repo, 101, hashlib.sha256(b'edited').hexdigest(), BASE, 'review-task-101'),
                       Policy(self.policy.repo, 101, DIGEST, '0' * 40, 'review-task-101')):
            self.assertEqual(self.bridge(policy).once()['status'], 'blocked')
        self.assertEqual(self.agent.calls, 0)

    def test_strict_local_authorization_two_synthetic_tasks(self):
        for number in (101, 102):
            with self.subTest(number=number), tempfile.TemporaryDirectory() as directory:
                body = f'Synthetic task {number}'
                record = {'repo': self.github.repo, 'issue': number,
                          'body_digest': hashlib.sha256(body.encode()).hexdigest(),
                          'base': 'b' * 40, 'branch': f'review-task-{number}'}
                path = Path(directory) / 'auth.json'
                path.write_text(json.dumps(record))
                path.chmod(0o600)
                policy = load_authorization(path)
                gh, agent = FakeGitHub(), FakeAgent()
                gh.policy = agent.policy = policy
                gh.number, gh.body = number, body
                gh.pr.update(body=draft_body(policy), title=draft_title(policy),
                             pinned_start=record['base'])
                agent.run = lambda prompt, worktree: {'head': HEAD, 'branch': policy.branch}
                bridge = Bridge(Path(directory) / 'state', policy, gh, agent, auth_path=path)
                self.assertEqual(bridge.once()['status'], 'review-ready')
                self.assertEqual(bridge.once()['status'], 'review-ready')
                self.assertEqual(doctor(bridge.state, policy)['status'], 'review-ready')
                self.assertEqual(Bridge(bridge.state, self.policy, gh, agent, auth_path=path).once()['status'], 'blocked')
                self.assertEqual(doctor(bridge.state, self.policy)['status'], 'blocked')

    def test_authorization_rejects_extra_fields_and_insecure_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'auth.json'
            record = {'repo': self.github.repo, 'issue': 101, 'body_digest': 'a' * 64,
                      'base': 'b' * 40, 'branch': 'review-task-101', 'command': 'echo unsafe'}
            path.write_text(json.dumps(record))
            path.chmod(0o600)
            with self.assertRaises(ValueError):
                load_authorization(path)
            del record['command']
            path.write_text(json.dumps(record))
            path.chmod(0o644)
            with self.assertRaises(PermissionError):
                load_authorization(path)

    def test_authorization_open_refuses_symlink_swap(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'auth.json'
            target = Path(directory) / 'target.json'
            target.write_text(json.dumps(asdict(self.policy)))
            target.chmod(0o600)
            path.write_text(target.read_text())
            path.chmod(0o600)
            actual_open = os.open
            def swap_before_open(name, flags, *args, **kwargs):
                if Path(name) == path:
                    path.unlink()
                    path.symlink_to(target)
                return actual_open(name, flags, *args, **kwargs)
            with patch('signal_desk.task_bridge.bridge.os.open', side_effect=swap_before_open):
                with self.assertRaises(OSError):
                    load_authorization(path)

    def test_authorization_read_is_bounded_even_if_file_grows_after_open(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'auth.json'
            path.write_text(json.dumps(asdict(self.policy)))
            path.chmod(0o600)
            actual_read = os.read
            requested = []
            def grow_before_read(fd, size):
                requested.append(size)
                with path.open('ab') as output:
                    output.write(b' ' * 100000)
                return actual_read(fd, size)
            with patch('signal_desk.task_bridge.bridge.os.read', side_effect=grow_before_read):
                with self.assertRaisesRegex(ValueError, 'bound|changed'):
                    load_authorization(path)
            self.assertEqual(requested, [2049])

    def test_legacy_issue_22_bootstrap_is_not_new_authority(self):
        with self.assertRaisesRegex(ValueError, 'authorization'):
            Policy(self.policy.repo, 22, DIGEST, BASE, 'new-branch-for-old-issue')

    def test_task_branch_cannot_be_the_protected_pr_target(self):
        with self.assertRaisesRegex(ValueError, 'authorization'):
            Policy(self.policy.repo, 101, DIGEST, BASE, 'main')

    def test_authorization_file_drift_after_publication_blocks_child(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'auth.json'
            path.write_text(json.dumps({'repo': self.policy.repo, 'issue': self.policy.issue,
                                        'body_digest': self.policy.body_digest, 'base': self.policy.base,
                                        'branch': self.policy.branch}))
            path.chmod(0o600)
            gh = FakeGitHub()
            original_publish = gh.publish
            def publish(repo, issue, text):
                receipt = original_publish(repo, issue, text)
                path.write_text(path.read_text().replace('review-task-101', 'review-task-102'))
                return receipt
            gh.publish = publish
            result = Bridge(Path(directory) / 'state', load_authorization(path), gh,
                            self.agent, auth_path=path).once()
            self.assertEqual(result['status'], 'blocked')
            self.assertEqual(self.agent.calls, 0)

    def test_reconciliation_rejects_changed_authorization_file_without_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'auth.json'
            record = {'repo': self.policy.repo, 'issue': 101, 'body_digest': DIGEST,
                      'base': BASE, 'branch': self.policy.branch}
            path.write_text(json.dumps(record))
            path.chmod(0o600)
            gh = FakeGitHub()
            bridge = Bridge(Path(directory) / 'state', load_authorization(path), gh,
                            self.agent, auth_path=path)
            bridge.once()
            before = list(gh.posts)
            record['branch'] = 'review-task-102'
            path.write_text(json.dumps(record))
            observation = bridge.reconcile()
            self.assertEqual(observation['status'], 'blocked')
            self.assertIn('authorization changed', observation['reason'])
            self.assertEqual(gh.posts, before)

    def test_duplicate_fields_and_malformed_authorization_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'auth.json'
            path.write_text('{"repo":"x","repo":"y"}')
            path.chmod(0o600)
            with self.assertRaises(ValueError):
                load_authorization(path)
            path.write_text('{bad json')
            with self.assertRaises(ValueError):
                load_authorization(path)

    def test_journal_branch_worktree_and_identity_tampering_blocks_readers(self):
        self.bridge().once()
        for column, value in (('branch', 'different-branch'), ('worktree', '/elsewhere'),
                              ('auth_identity', '0' * 64)):
            with self.subTest(column=column):
                with sqlite3.connect(self.state / 'journal.sqlite3') as db:
                    original = db.execute(f'SELECT {column} FROM runs').fetchone()[0]
                    db.execute(f'UPDATE runs SET {column}=?', (value,))
                self.assertEqual(self.bridge().once()['status'], 'blocked')
                self.assertEqual(self.bridge().reconcile()['status'], 'blocked')
                self.assertEqual(doctor(self.state, self.policy)['status'], 'blocked')
                with sqlite3.connect(self.state / 'journal.sqlite3') as db:
                    db.execute(f'UPDATE runs SET {column}=?', (original,))
        self.assertEqual(self.agent.calls, 1)


if __name__ == '__main__':
    unittest.main()
