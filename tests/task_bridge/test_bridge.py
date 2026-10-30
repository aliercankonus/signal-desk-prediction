import hashlib
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from signal_desk.task_bridge.bridge import Bridge, Policy, doctor

BODY = (Path(__file__).parent / 'issue22.txt').read_text()
DIGEST = hashlib.sha256(BODY.encode()).hexdigest()
BASE = 'a930a3c715635341e62538a3cc15a260162f6be9'
HEAD = 'f' * 40


class FakeGitHub:
    def __init__(self):
        self.repo = 'aliercankonus/signal-desk-prediction'
        self.number = 22
        self.body = BODY
        self.state = 'open'
        self.issue_calls = 0
        self.edit_on_second_issue_read = False
        self.posts = []
        self.fail_post = set()
        self.pr = {'url': 'https://github.com/aliercankonus/signal-desk-prediction/pull/42',
                   'draft': True, 'head': HEAD, 'base': BASE, 'body': 'Refs #22',
                   'ci': 'success', 'ci_head': HEAD}

    def issue(self, repo, number):
        self.issue_calls += 1
        body = 'edited after initial authorization' if (self.edit_on_second_issue_read and
                                                        self.issue_calls >= 2) else self.body
        return {'repo': self.repo, 'number': self.number, 'body': body, 'state': self.state}

    def draft_pr(self, repo, branch):
        return self.pr

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
        return {'head': HEAD, 'branch': 'issue-22-bridge'}


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name) / 'private'
        self.github = FakeGitHub()
        self.agent = FakeAgent()
        self.policy = Policy('aliercankonus/signal-desk-prediction', 22, DIGEST, BASE)

    def bridge(self, policy=None):
        return Bridge(self.state, policy or self.policy, self.github, self.agent)

    def test_once_records_before_invocation_and_duplicate_poll_does_not_redispatch(self):
        def inspect():
            row = self.bridge().status()
            self.assertEqual(row['status'], 'running')
            self.assertEqual(row['base'], BASE)
            self.assertEqual(row['body_digest'], DIGEST)
            self.assertEqual(row['branch'], 'issue-22-bridge')
            self.assertTrue(row['worktree'])
        self.agent.action = inspect
        self.assertEqual(self.bridge().once()['status'], 'review-ready')
        self.assertEqual(self.bridge().once()['status'], 'review-ready')
        self.assertEqual(self.agent.calls, 1)
        self.assertEqual([json.loads(m)['status'] for m in self.github.posts],
                         ['queued', 'running', 'review-ready'])
        self.assertIn(HEAD, self.github.posts[-1])

    def test_stored_run_from_other_issue_cannot_report_ready(self):
        self.assertEqual(self.bridge().once()['status'], 'review-ready')
        with sqlite3.connect(self.state / 'journal.sqlite3') as db:
            db.execute('UPDATE runs SET issue_number=23')
        self.assertEqual(doctor(self.state)['status'], 'blocked')
        result = self.bridge().once()
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(self.agent.calls, 1)

    def test_duplicate_poll_does_not_report_stale_review_ready_after_pr_disappears(self):
        self.assertEqual(self.bridge().once()['status'], 'review-ready')
        self.github.pr = None
        result = self.bridge().once()
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(self.agent.calls, 1)

    def test_duplicate_poll_blocks_if_draft_pr_issue_link_is_removed(self):
        self.assertEqual(self.bridge().once()['status'], 'review-ready')
        self.github.pr['body'] = 'No issue link remains'
        result = self.bridge().once()
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(doctor(self.state)['status'], 'blocked')
        self.assertEqual(self.bridge().status()['status'], 'blocked')
        self.assertEqual(self.agent.calls, 1)

    def test_incomplete_journal_blocks_once_doctor_and_reconcile(self):
        self.state.mkdir(mode=0o700)
        sqlite3.connect(self.state / 'journal.sqlite3').close()
        self.assertEqual(self.bridge().once()['status'], 'blocked')
        self.assertEqual(doctor(self.state)['status'], 'blocked')
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
            observed.append((doctor(self.state)['status'], self.bridge().status()['status']))
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
        self.agent.run = lambda prompt, worktree: {'head': 'secret=/private/token', 'branch': 'issue-22-bridge'}
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
        self.assertEqual(seen[0]['head'], HEAD)
        self.assertEqual(seen[0]['operator_review'], True)
        self.assertTrue(seen[0]['publication_consistent'])
        self.assertEqual(len(self.github.posts), 3)

    def test_journal_is_private_and_bounded_to_one_run(self):
        self.bridge().once()
        self.assertEqual((self.state / 'journal.sqlite3').stat().st_mode & 0o777, 0o600)
        with sqlite3.connect(self.state / 'journal.sqlite3') as db:
            self.assertEqual(db.execute('SELECT count(*) FROM runs').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT issue_number FROM runs').fetchone()[0], 22)
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
        for policy in (Policy('other/repo', 22, DIGEST, BASE),
                       Policy(self.policy.repo, 23, DIGEST, BASE),
                       Policy(self.policy.repo, 22, hashlib.sha256(b'edited').hexdigest(), BASE),
                       Policy(self.policy.repo, 22, DIGEST, '0' * 40)):
            self.assertEqual(self.bridge(policy).once()['status'], 'blocked')
        self.assertEqual(self.agent.calls, 0)


if __name__ == '__main__':
    unittest.main()
