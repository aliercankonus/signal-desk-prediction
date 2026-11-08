"""Root-only verifier regressions; no network, worker imports or host effects."""
import base64
import importlib.util
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('bridge_readback', ROOT / 'ops/bridge_one_shot/bridge_readback.py')
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)

REPO = 'aliercankonus/signal-desk-prediction'
BASE = 'e84021a786004456a12de9e25eae50d191da6cf1'
BRANCH = 'issue43-one-shot-review-note'
HEAD = 'a' * 40
TIP = 'c' * 40
RUN = 'b' * 32
QUEUE = 'd' * 32
URL = f'https://github.com/{REPO}/pull/123'
BODY = f'Refs #43\n\nReviewed task branch: `{BRANCH}`.\n'
TASK = (ROOT / 'tests/task_bridge/fixtures/issue43_body.txt').read_text(encoding='utf-8')
DIGEST = hashlib.sha256(TASK.encode()).hexdigest()
ARTIFACT = TASK.split('```markdown\n', 1)[1].split('\n```', 1)[0].encode() + b'\n'
ARTIFACT_PATH = 'docs/ONE_SHOT_REVIEW_NOTE.md'
ARTIFACT_BLOB = hashlib.sha1(b'blob ' + str(len(ARTIFACT)).encode() + b'\0' + ARTIFACT).hexdigest()
assert DIGEST == 'c9e4e393ccc506954f0a18e6eaeea7c82ff598b0b41eac642d7f88da1fca73c6'


def fixture(tmp_path):
    queue = tmp_path / 'host-private' / 'queue'
    state = queue / QUEUE / 'bridge'
    state.mkdir(parents=True)
    db = state / 'journal.sqlite3'
    with sqlite3.connect(db) as conn:
        conn.executescript('CREATE TABLE runs (run_id,repo,issue_number,status,base,body_digest,branch,worktree,head,pr_url,ci,target_tip,auth_identity);'
                           'CREATE TABLE pr_creations (id,stage,expected_head,number,url);'
                           'CREATE TABLE publications (id,status,comment_id,recorded_at);')
        conn.execute('INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                     (RUN, REPO, 43, 'review-ready', BASE, DIGEST, BRANCH,
                      f'/state/queue/{QUEUE}/bridge/worktrees/{RUN}', HEAD, URL, 'pending', TIP, 'e'*64))
        conn.execute('INSERT INTO pr_creations VALUES (1,?,?,?,?)', ('verified', HEAD, 123, URL))
        conn.execute('INSERT INTO publications VALUES (1,?,?,?)', ('queued', 11, 'now'))
        conn.execute('INSERT INTO publications VALUES (2,?,?,?)', ('running', 12, 'now'))
        conn.execute('INSERT INTO publications VALUES (3,?,?,?)', ('review-ready', 13, 'now'))
    payload = {'status': 'review-ready', 'run_id': RUN, 'base': BASE, 'auth_identity': 'e'*64,
               'head': HEAD, 'pr_url': URL, 'ci': 'pending', 'target_tip': TIP}
    comments = {11: {'status':'queued', 'run_id':RUN, 'base':BASE, 'auth_identity':'e'*64},
                12: {'status':'running', 'run_id':RUN, 'base':BASE, 'auth_identity':'e'*64},
                13: payload}
    api = {
        '/user': {'login': 'operator'},
        f'/repos/{REPO}/issues/43': {'number':43,'state':'open','body':TASK},
        f'/repos/{REPO}/git/ref/heads/{BRANCH}': {'ref':f'refs/heads/{BRANCH}',
            'url':f'https://api.github.com/repos/{REPO}/git/refs/heads/{BRANCH}',
            'object':{'type':'commit','sha':HEAD,'url':f'https://api.github.com/repos/{REPO}/git/commits/{HEAD}'}},
        f'/repos/{REPO}/git/ref/heads/main': {'ref':'refs/heads/main',
            'url':f'https://api.github.com/repos/{REPO}/git/refs/heads/main',
            'object':{'type':'commit','sha':TIP,'url':f'https://api.github.com/repos/{REPO}/git/commits/{TIP}'}},
        f'/repos/{REPO}/pulls?state=open&head=aliercankonus%3A{BRANCH}&per_page=2': [
            {'number':123,'html_url':URL,'state':'open','draft':True,'title':'Task bridge draft for issue #43',
             'body':BODY,'head':{'ref':BRANCH,'sha':HEAD,'repo':{'full_name':REPO}},
             'base':{'ref':'main','repo':{'full_name':REPO}}}],
        f'/repos/{REPO}/compare/{BASE}...{HEAD}': {'status':'ahead','merge_base_commit':{'sha':BASE},
            'files':[{'filename':ARTIFACT_PATH,'status':'added','sha':ARTIFACT_BLOB,'additions':7,'deletions':0}]},
        f'/repos/{REPO}/contents/{ARTIFACT_PATH}?ref={HEAD}': {'type':'file','path':ARTIFACT_PATH,
            'encoding':'base64','size':len(ARTIFACT),'content':base64.b64encode(ARTIFACT).decode(),
            'sha':ARTIFACT_BLOB},
        f'/repos/{REPO}/commits/{HEAD}/check-runs?per_page=100': {'total_count':1,'check_runs':[{'head_sha':HEAD,'status':'in_progress'}]},
        f'/repos/{REPO}/actions/runs?head_sha={HEAD}&per_page=100': {'total_count':0,'workflow_runs':[]},
        f'/repos/{REPO}/commits/{HEAD}/status': {'sha':HEAD,'statuses':[]},
    }
    for ident, value in comments.items():
        api[f'/repos/{REPO}/issues/comments/{ident}'] = {'id': ident, 'body':json.dumps(value),
             'issue_url':f'https://api.github.com/repos/{REPO}/issues/43','user':{'login':'operator'}}
    api[f'/repos/{REPO}/issues/43/comments?per_page=100&page=1'] = [
        api[f'/repos/{REPO}/issues/comments/{ident}'] for ident in comments]
    return queue, db, api


def verify(queue, api):
    return module.verify(queue, QUEUE, DIGEST, 'e'*64, lambda path: api[path])


def test_root_verifier_authenticates_remote_identity_without_worker_imports(tmp_path, monkeypatch):
    queue, db, api = fixture(tmp_path)
    monkeypatch.setitem(sys.modules, 'signal_desk.task_bridge.bridge', None)
    assert verify(queue, api) == {'verified':True, 'run_id':RUN, 'head':HEAD, 'pr_url':URL, 'observed_ci':'pending'}
    assert not (db.parent / 'journal.sqlite3-wal').exists()


def test_historical_pending_receipt_can_progress_to_current_success(tmp_path):
    queue, _, api = fixture(tmp_path)
    checks = api[f'/repos/{REPO}/commits/{HEAD}/check-runs?per_page=100']['check_runs']
    checks[0].update(status='completed', conclusion='success')
    assert verify(queue, api)['observed_ci'] == 'success'


def test_host_database_path_is_not_the_container_worktree_identity(tmp_path):
    queue, db, api = fixture(tmp_path)
    assert verify(queue, api)['verified'] is True
    with sqlite3.connect(db) as conn:
        conn.execute('UPDATE runs SET worktree=?', (str(queue / QUEUE / 'bridge' / 'worktrees' / RUN),))
    assert verify(queue, api)['verified'] is False


def test_artifact_bytes_are_from_frozen_issue_not_a_worker_digest(tmp_path):
    queue, _, api = fixture(tmp_path)
    assert verify(queue, api)['verified'] is True
    api[f'/repos/{REPO}/issues/43']['body'] = TASK.replace('A draft PR is reviewable',
                                                              'A draft PR is runnable')
    assert verify(queue, api)['verified'] is False


@pytest.mark.parametrize('change', ['extra_file', 'modified_file', 'wrong_bytes', 'missing_newline',
                                    'wrong_blob_sha', 'wrong_contents_path', 'wrong_encoding'])
def test_frozen_artifact_scope_or_bytes_cannot_be_substituted(tmp_path, change):
    queue, _, api = fixture(tmp_path)
    assert verify(queue, api)['verified'] is True
    compare = api[f'/repos/{REPO}/compare/{BASE}...{HEAD}']
    content = api[f'/repos/{REPO}/contents/{ARTIFACT_PATH}?ref={HEAD}']
    if change == 'extra_file':
        compare['files'].append({'filename':'src/other.py','status':'added'})
    elif change == 'modified_file':
        compare['files'][0]['status'] = 'modified'
    elif change == 'wrong_blob_sha':
        compare['files'][0]['sha'] = '9' * 40
    elif change == 'wrong_contents_path':
        content['path'] = 'docs/OTHER.md'
    elif change == 'wrong_encoding':
        content['encoding'] = 'utf-8'
    else:
        wrong = ARTIFACT.rstrip(b'\n') if change == 'missing_newline' else ARTIFACT + b'forged\n'
        content['content'] = base64.b64encode(wrong).decode()
        content['size'] = len(wrong)
    assert verify(queue, api)['verified'] is False


def test_worker_forged_json_or_remote_branch_does_not_verify(tmp_path):
    queue, _, api = fixture(tmp_path)
    api[f'/repos/{REPO}/git/ref/heads/{BRANCH}']['object']['sha'] = '9'*40
    assert verify(queue, api)['verified'] is False


def test_unconfirmed_publication_and_wrong_remote_author_fail_closed(tmp_path):
    queue, db, api = fixture(tmp_path)
    with sqlite3.connect(db) as conn:
        conn.execute('UPDATE publications SET comment_id=NULL WHERE id=3')
    assert verify(queue, api)['verified'] is False
    with sqlite3.connect(db) as conn:
        conn.execute('UPDATE publications SET comment_id=13 WHERE id=3')
    api[f'/repos/{REPO}/issues/comments/13']['user']['login'] = 'worker'
    assert verify(queue, api)['verified'] is False


def test_queue_run_pr_ci_and_receipt_mismatch_fail_closed(tmp_path):
    queue, db, api = fixture(tmp_path)
    assert module.verify(queue, '0'*32, DIGEST, 'e'*64, lambda path: api[path])['verified'] is False
    with sqlite3.connect(db) as conn:
        conn.execute('UPDATE runs SET run_id=?', ('0'*32,))
    assert verify(queue, api)['verified'] is False
    with sqlite3.connect(db) as conn:
        conn.execute('UPDATE runs SET run_id=?', (RUN,))
        conn.execute('UPDATE pr_creations SET expected_head=?', ('9'*40,))
    assert verify(queue, api)['verified'] is False
    with sqlite3.connect(db) as conn:
        conn.execute('UPDATE pr_creations SET expected_head=?', (HEAD,))
    api[f'/repos/{REPO}/commits/{HEAD}/check-runs?per_page=100']['check_runs'][0]['head_sha'] = '9'*40
    assert verify(queue, api)['verified'] is False


def test_remote_exception_is_not_verified(tmp_path):
    queue, _, api = fixture(tmp_path)
    del api[f'/repos/{REPO}/issues/43']
    assert verify(queue, api)['verified'] is False
