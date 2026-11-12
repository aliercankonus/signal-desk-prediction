#!/usr/bin/env python3
"""Root-only pinned readback: no imports or predicates from the writable worker.

The root operator invokes verify() from the hash-checked private bundle with its
own authenticated read-only GitHub GET client. Worker journal values are only
claims; every publication, draft, branch and exact-head CI is independently
observed. Never install or execute this module inside the worker container.
"""
import base64
import binascii
import hashlib
import json
from pathlib import Path
import re
import sqlite3

REPO = 'aliercankonus/signal-desk-prediction'
PIN = 'e84021a786004456a12de9e25eae50d191da6cf1'
BRANCH = 'issue43-one-shot-a2'
CONTAINER_QUEUE = Path('/state/queue')
ARTIFACT = 'docs/ONE_SHOT_REVIEW_NOTE.md'
HEX32 = re.compile(r'[0-9a-f]{32}\Z')
HEX40 = re.compile(r'[0-9a-f]{40}\Z')
HEX64 = re.compile(r'[0-9a-f]{64}\Z')


def _expect(condition):
    if not condition:
        raise ValueError('independent readback mismatch')


def _artifact_bytes(body):
    """Derive approved bytes solely from the independently fetched frozen issue."""
    marker = '```markdown\n'
    _expect(isinstance(body, str) and body.count(marker) == 1 and
            body.count('\n```\n') == 1 and
            f'Create exactly one English Markdown documentation file, `{ARTIFACT}`' in body)
    note = body.split(marker, 1)[1].split('\n```\n', 1)[0].encode('utf-8') + b'\n'
    _expect(0 < len(note) <= 8192)
    return note


def _check_artifact(compare, head, body, get, base_path):
    expected = _artifact_bytes(body)
    files = compare.get('files')
    _expect(isinstance(files, list) and len(files) == 1)
    entry = files[0]
    _expect(entry.get('filename') == ARTIFACT and entry.get('status') == 'added' and
            isinstance(entry.get('sha'), str) and HEX40.fullmatch(entry['sha']))
    record = get(base_path + '/contents/' + ARTIFACT + '?ref=' + head)
    _expect(record.get('type') == 'file' and record.get('path') == ARTIFACT and
            record.get('encoding') == 'base64' and record.get('sha') == entry['sha'] and
            record.get('size') == len(expected) and isinstance(record.get('content'), str) and
            len(record['content']) <= 16384)
    try:
        actual = base64.b64decode(''.join(record['content'].split()), validate=True)
    except (ValueError, binascii.Error):
        raise ValueError('invalid artifact encoding') from None
    _expect(actual == expected and
            hashlib.sha1(b'blob ' + str(len(actual)).encode() + b'\0' + actual).hexdigest() == entry['sha'])


def _verified(queue, queue_id, digest, identity, get):
    _expect(HEX32.fullmatch(queue_id) and HEX64.fullmatch(digest) and HEX64.fullmatch(identity))
    db = Path(queue) / queue_id / 'bridge' / 'journal.sqlite3'
    _expect(db.is_file() and not db.is_symlink())
    with sqlite3.connect(db.as_uri() + '?mode=ro', uri=True, timeout=1) as conn:
        conn.execute('PRAGMA query_only=ON')
        rows = conn.execute('SELECT run_id,repo,issue_number,status,base,body_digest,branch,worktree,head,pr_url,ci,target_tip,auth_identity FROM runs LIMIT 2').fetchall()
        creations = conn.execute('SELECT id,stage,expected_head,number,url FROM pr_creations LIMIT 2').fetchall()
        publications = conn.execute('SELECT status,comment_id FROM publications ORDER BY id LIMIT 5').fetchall()
    _expect(len(rows) == len(creations) == 1 and len(publications) == 3)
    run, repo, issue, status, base, body_digest, branch, worktree, head, url, ci, tip, auth = rows[0]
    _expect(HEX32.fullmatch(run) and (repo, issue, status, base, body_digest, branch, auth) ==
            (REPO, 43, 'review-ready', PIN, digest, BRANCH, identity))
    # The DB is opened through the host bind source; Bridge recorded the path
    # in its container namespace, not this root process's host namespace.
    _expect(worktree == str(CONTAINER_QUEUE / queue_id / 'bridge' / 'worktrees' / run))
    _expect(isinstance(head, str) and HEX40.fullmatch(head) and isinstance(tip, str) and HEX40.fullmatch(tip) and
            ci in ('success', 'failure', 'pending', 'unknown'))
    number = creations[0][3]
    _expect(type(number) is int and number > 0 and creations[0] ==
            (1, 'verified', head, number, f'https://github.com/{REPO}/pull/{number}') and url == creations[0][4])
    _expect([s for s, _ in publications] == ['queued', 'running', 'review-ready'] and
            all(type(i) is int and i > 0 for _, i in publications))
    base_path = '/repos/' + REPO
    task = get(base_path + '/issues/43')
    _expect(task.get('number') == 43 and task.get('state') == 'open' and
            hashlib.sha256(task['body'].encode('utf-8')).hexdigest() == digest)
    actor = get('/user')['login']
    _expect(isinstance(actor, str) and bool(actor))
    expected = {}
    for stage, comment_id in publications:
        payload = {'status': stage, 'run_id': run, 'base': PIN, 'auth_identity': identity}
        if stage == 'review-ready':
            payload.update(head=head, pr_url=url, ci=ci, target_tip=tip)
        expected[comment_id] = json.dumps(payload)
        row = get(base_path + '/issues/comments/' + str(comment_id))
        _expect(row.get('id') == comment_id and row.get('issue_url') ==
                f'https://api.github.com{base_path}/issues/43' and
                row.get('user', {}).get('login') == actor and row.get('body') == expected[comment_id])
    found = []
    for page in range(1, 6):
        comments = get(base_path + f'/issues/43/comments?per_page=100&page={page}')
        _expect(isinstance(comments, list) and len(comments) <= 100)
        for row in comments:
            if row.get('id') in expected and row.get('body') == expected[row['id']] and row.get('user', {}).get('login') == actor:
                found.append(row['id'])
        if len(comments) < 100:
            break
    else:
        raise ValueError('unbounded issue history')
    _expect(sorted(found) == sorted(expected))
    branch_ref = get(base_path + '/git/ref/heads/' + BRANCH)
    target_ref = get(base_path + '/git/ref/heads/main')
    _expect(branch_ref.get('ref') == 'refs/heads/' + BRANCH and
            branch_ref.get('object', {}).get('type') == 'commit' and
            branch_ref['object'].get('sha') == head and
            target_ref.get('ref') == 'refs/heads/main' and
            target_ref.get('object', {}).get('type') == 'commit' and
            target_ref['object'].get('sha') == tip)
    candidates = get(base_path + '/pulls?state=open&head=aliercankonus%3A' + BRANCH + '&per_page=2')
    _expect(isinstance(candidates, list) and len(candidates) == 1)
    pr = candidates[0]
    _expect(pr.get('number') == number and pr.get('html_url') == url and
            pr.get('state') == 'open' and pr.get('draft') is True and
            pr.get('title') == 'Task bridge draft for issue #43' and
            pr.get('body') == f'Refs #43\n\nReviewed task branch: `{BRANCH}`.\n' and
            pr.get('head', {}).get('ref') == BRANCH and pr['head'].get('sha') == head and
            pr['head'].get('repo', {}).get('full_name') == REPO and
            pr.get('base', {}).get('ref') == 'main' and pr['base'].get('repo', {}).get('full_name') == REPO)
    compare = get(base_path + '/compare/' + PIN + '...' + head)
    _expect(compare.get('status') in ('ahead', 'identical') and compare.get('merge_base_commit', {}).get('sha') == PIN)
    _check_artifact(compare, head, task['body'], get, base_path)
    checks = get(base_path + '/commits/' + head + '/check-runs?per_page=100')
    workflows = get(base_path + '/actions/runs?head_sha=' + head + '&per_page=100')
    legacy = get(base_path + '/commits/' + head + '/status')
    check_list, run_list = checks['check_runs'], workflows['workflow_runs']
    _expect(checks.get('total_count', len(check_list)) == len(check_list) and
            workflows.get('total_count', len(run_list)) == len(run_list) and
            len(check_list) <= 100 and len(run_list) <= 100 and legacy.get('sha') == head and
            all(unit.get('head_sha') == head for unit in check_list + run_list))
    states = [unit.get('conclusion') if unit.get('status') == 'completed' else 'pending'
              for unit in check_list + run_list]
    states += [unit.get('state') for unit in legacy.get('statuses', [])]
    observed = ('unknown' if not states else
                'failure' if any(s in ('failure', 'timed_out', 'cancelled', 'action_required') for s in states) else
                'success' if all(s == 'success' for s in states) else 'pending')
    # Journal/issue receipt is a historical snapshot; this is the current
    # independently fetched exact-head CI state, which may have progressed.
    return {'verified': True, 'run_id': run, 'head': head, 'pr_url': url, 'observed_ci': observed}


def verify(queue, queue_id, digest, identity, get):
    """Fail closed on an untrusted journal or inconclusive remote observation."""
    try:
        return _verified(queue, queue_id, digest, identity, get)
    except (ValueError, TypeError, KeyError, AttributeError, IndexError, sqlite3.Error, OSError):
        return {'verified': False}
