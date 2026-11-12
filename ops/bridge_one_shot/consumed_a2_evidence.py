"""Read-only bounded existing a2 metadata. No CLI, auth, Git, Docker or task.
Historical stdout was discarded and cannot be recovered by this module.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys
import time
import types
ATTEMPT = 'issue41-cold-20261110-01'
QUEUE = '7859a7198b8948ce953c1759feb106ce'
RUN = '2a07298e691f47558826903aef0b2a3d'
AUTH = '1da74bf1d715dc3c0a78809955a2401744e85f64014bdbb57a1e9626e001c037'
PIN = 'e84021a786004456a12de9e25eae50d191da6cf1'
STAGES = {'preflight', 'child_invocation', 'child_completion', 'local_result_verification', 'authority_verification', 'remote_draft_discovery', 'pr_create_intent', 'pr_create_response', 'pr_create_readback', 'status_publication'}
CATEGORIES = {'preflight_failed', 'child_nonzero', 'child_signaled', 'child_timeout', 'child_interrupted', 'child_unknown', 'result_invalid', 'authority_changed', 'authority_unavailable', 'publication_failed', 'draft_failed', 'journal_failed', 'operation_failed'}
STOPS = {'exit_zero', 'exit_nonzero', 'signal', 'timeout', 'interrupted', 'unknown', 'spawn_failed'}
CHECKPOINTS = {'child-intent', 'pre-tests', 'post-tests', 'pre-commit', 'post-commit', 'pre-push', 'post-push', 'pushed-head-verified', 'child-completed', 'pre-pr-publication', 'post-pr-publication', 'paused', 'worktree-created'}
PHASES = {'created', 'preflight', 'start_isolation', 'login', 'github_reads', 'enroll_disabled', 'enable_inbox', 'one_bridge_claim', 'reconcile', 'cleanup', 'report', 'blocked'}
STATUS = {'queued', 'running', 'claimed', 'blocked', 'review-ready', 'pending'}

class Stop(Exception):
    pass

def directory(path, uid, private=True):
    for p in (path, *path.parents):
        s = p.lstat()
        if not stat.S_ISDIR(s.st_mode) or s.st_uid not in (0, uid) or s.st_mode & 18:
            raise Stop('UNSAFE_ANCESTRY')
    s = path.lstat()
    if s.st_uid != uid or (private and stat.S_IMODE(s.st_mode) != 448):
        raise Stop('DIRECTORY_METADATA')

def read_bytes(path, uid, limit=16384, mode=384):
    directory(path.parent, uid, private=False)
    s = path.lstat()
    if not stat.S_ISREG(s.st_mode) or s.st_uid != uid or s.st_nlink != 1 or (stat.S_IMODE(s.st_mode) != mode) or (not 0 < s.st_size <= limit):
        raise Stop('FILE_METADATA')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as f:
        t = os.fstat(f.fileno())
        data = f.read(limit + 1)
    identity = lambda v: (v.st_dev, v.st_ino, v.st_uid, v.st_mode, v.st_size, v.st_mtime_ns, v.st_ctime_ns, v.st_nlink)
    if not identity(s) == identity(t) == identity(path.lstat()) or len(data) != s.st_size:
        raise Stop('FILE_CHANGED')
    return data

def enum(value, allowed):
    return value if isinstance(value, str) and value in allowed else 'UNVERIFIED'

def number(value):
    return value if type(value) is int and 0 <= value <= 3600000 else None

def head(value):
    return value if isinstance(value, str) and re.fullmatch('[0-9a-f]{40}', value) else None

def database(path, uid=10000):
    directory(path.parent, uid)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_uid != uid or before.st_nlink != 1 or before.st_mode & 63 or (before.st_size > 2097152):
        raise Stop('DB_METADATA')
    for suffix in ('-wal', '-shm', '-journal'):
        if os.path.lexists(str(path) + suffix):
            raise Stop('DB_SIDECAR_PRESERVE')
    connection = sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True, timeout=2)
    try:
        connection.enable_load_extension(False)
        connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 65536)
        connection.execute('PRAGMA trusted_schema=OFF')
        connection.execute('PRAGMA query_only=ON')
        fuel = [0]

        def progress():
            fuel[0] += 1
            return 1 if fuel[0] > 200 else 0
        connection.set_progress_handler(progress, 1000)
        tables = dict(connection.execute("SELECT name,type FROM sqlite_master WHERE name IN ('runs','failures','stage_events','pr_creations')").fetchall())
        if tables != {name: 'table' for name in ('runs', 'failures', 'stage_events', 'pr_creations')}:
            raise Stop('DB_SCHEMA')
        runs = connection.execute('SELECT run_id,status,auth_identity,base,branch,worktree,head,pr_url FROM runs LIMIT 2').fetchall()
        events = connection.execute('SELECT stage,duration_ms,exit_code,signal_number,stop_reason FROM stage_events ORDER BY id LIMIT 33').fetchall()
        failures = connection.execute('SELECT stage,category,exit_code,signal_number,duration_ms,stop_reason FROM failures LIMIT 2').fetchall()
        creations = connection.execute('SELECT stage,expected_head,number FROM pr_creations LIMIT 2').fetchall()
    finally:
        connection.close()
    after = path.lstat()
    identity = lambda v: (v.st_dev, v.st_ino, v.st_uid, v.st_mode, v.st_size, v.st_mtime_ns, v.st_ctime_ns)
    if identity(before) != identity(after):
        raise Stop('DB_CHANGED')
    if len(runs) != 1 or len(events) > 32 or len(failures) > 1 or (len(creations) > 1):
        raise Stop('DB_BOUND')
    row = runs[0]
    expected_worktree = '/state/queue/' + QUEUE + '/bridge/worktrees/' + RUN
    if row[0] != RUN or row[2:6] != (AUTH, PIN, 'issue43-one-shot-a2', expected_worktree):
        raise Stop('RUN_IDENTITY')
    result = {'status': enum(row[1], STATUS), 'head': head(row[6]), 'pr_recorded': row[7] is not None, 'stages': [enum(e[0], STAGES) for e in events]}
    if failures:
        f = failures[0]
        result['failure'] = dict(stage=enum(f[0], STAGES), category=enum(f[1], CATEGORIES), exit_code=number(f[2]), signal=number(f[3]), duration_ms=number(f[4]), stop_reason=enum(f[5], STOPS))
    else:
        result['failure'] = None
    completions = [e for e in events if e[0] == 'child_completion']
    if completions:
        e = completions[-1]
        result['child_completion'] = dict(duration_ms=number(e[1]), exit_code=number(e[2]), signal=number(e[3]), stop_reason=enum(e[4], STOPS))
    if creations:
        c = creations[0]
        result['pr_creation'] = dict(stage=enum(c[0], {'intent', 'responded', 'verified', 'reused'}), head=head(c[1]), number=number(c[2]))
    return (result, expected_worktree)


def inspect_queue(queue_root,uid=10000):
    root=Path(queue_root)
    if root.name!=QUEUE or not root.is_absolute():raise Stop('EXACT_QUEUE')
    entry=json.loads(read_bytes(root/'state.json',uid))
    if (entry.get('id')!=QUEUE or entry.get('bridge_run_id')!=RUN or entry.get('authorization_identity')!=AUTH or entry.get('invocations')!=1 or entry.get('status')!='blocked'):
        raise Stop('EXACT_CONSUMED_ENTRY')
    data,_=database(root/'bridge'/'journal.sqlite3',uid)
    return dict(diagnostic='consumed-a2-metadata-v1',queue_id=QUEUE,run_id=RUN,bridge=data,retry=False,
        note='historical raw stdout discarded; no provider cause inferred')
