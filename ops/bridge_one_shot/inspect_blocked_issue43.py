"""Inspect only the consumed #43 attempt; optionally post one sanitized report.

Never runs a child, Git, Docker, cleanup, login, sign, enrollment or dispatch.
--report uses only the existing root GitHub reporting credential and creates a
new root-only report intent/receipt. An existing intent always refuses replay.
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

ATTEMPT='issue41-cold-20261110-01'
QUEUE='2f175fc762d5476c8938472c7f784094'
RUN='a4db0f8a32ea451ab0ae0e1aa55ba768'
AUTH='2cc0a42be444e93491b14f37bd9fdbd0c71e65d30305d7b79c24b32c94c59cfa'
PIN='e84021a786004456a12de9e25eae50d191da6cf1'
SIGNER_SHA='d7d9cae83ae0e0b728574b998f9241df9f6e12c51e12ed87025cfce1916d61fd'
STAGES={'preflight','child_invocation','child_completion','local_result_verification','authority_verification',
    'remote_draft_discovery','pr_create_intent','pr_create_response','pr_create_readback','status_publication'}
CATEGORIES={'preflight_failed','child_nonzero','child_signaled','child_timeout','child_interrupted','child_unknown',
    'result_invalid','authority_changed','authority_unavailable','publication_failed','draft_failed','journal_failed','operation_failed'}
STOPS={'exit_zero','exit_nonzero','signal','timeout','interrupted','unknown','spawn_failed'}
CHECKPOINTS={'child-intent','pre-tests','post-tests','pre-commit','post-commit','pre-push','post-push',
    'pushed-head-verified','child-completed','pre-pr-publication','post-pr-publication','paused','worktree-created'}
PHASES={'created','preflight','start_isolation','login','github_reads','enroll_disabled','enable_inbox',
    'one_bridge_claim','reconcile','cleanup','report','blocked'}
STATUS={'queued','running','claimed','blocked','review-ready','pending'}

class Stop(Exception):pass


def directory(path,uid,private=True):
    for p in (path,*path.parents):
        s=p.lstat()
        if not stat.S_ISDIR(s.st_mode) or s.st_uid not in (0,uid) or s.st_mode&0o022:raise Stop('UNSAFE_ANCESTRY')
    s=path.lstat()
    if s.st_uid!=uid or private and stat.S_IMODE(s.st_mode)!=0o700:raise Stop('DIRECTORY_METADATA')


def read_bytes(path,uid,limit=16384,mode=0o600):
    directory(path.parent,uid,private=False)
    s=path.lstat()
    if not stat.S_ISREG(s.st_mode) or s.st_uid!=uid or s.st_nlink!=1 or stat.S_IMODE(s.st_mode)!=mode or not 0<s.st_size<=limit:
        raise Stop('FILE_METADATA')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as f:
        t=os.fstat(f.fileno());data=f.read(limit+1)
    identity=lambda v:(v.st_dev,v.st_ino,v.st_uid,v.st_mode,v.st_size,v.st_mtime_ns,v.st_ctime_ns,v.st_nlink)
    if not identity(s)==identity(t)==identity(path.lstat()) or len(data)!=s.st_size:raise Stop('FILE_CHANGED')
    return data


def enum(value,allowed):return value if isinstance(value,str) and value in allowed else 'UNVERIFIED'
def number(value):return value if type(value) is int and 0<=value<=3600000 else None
def head(value):return value if isinstance(value,str) and re.fullmatch('[0-9a-f]{40}',value) else None


def database(path,uid=10000):
    directory(path.parent,uid)
    before=path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_uid!=uid or before.st_nlink!=1 or before.st_mode&0o077 or before.st_size>2097152:
        raise Stop('DB_METADATA')
    for suffix in ('-wal','-shm','-journal'):
        if os.path.lexists(str(path)+suffix):raise Stop('DB_SIDECAR_PRESERVE')
    connection=sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1',uri=True,timeout=2)
    try:
        connection.enable_load_extension(False)
        connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH,65536)
        connection.execute('PRAGMA trusted_schema=OFF');connection.execute('PRAGMA query_only=ON')
        fuel=[0]
        def progress():
            fuel[0]+=1;return 1 if fuel[0]>200 else 0
        connection.set_progress_handler(progress,1000)
        tables=dict(connection.execute("SELECT name,type FROM sqlite_master WHERE name IN ('runs','failures','stage_events','pr_creations')").fetchall())
        if tables!={name:'table' for name in ('runs','failures','stage_events','pr_creations')}:raise Stop('DB_SCHEMA')
        runs=connection.execute('SELECT run_id,status,auth_identity,base,branch,worktree,head,pr_url FROM runs LIMIT 2').fetchall()
        events=connection.execute('SELECT stage,duration_ms,exit_code,signal_number,stop_reason FROM stage_events ORDER BY id LIMIT 33').fetchall()
        failures=connection.execute('SELECT stage,category,exit_code,signal_number,duration_ms,stop_reason FROM failures LIMIT 2').fetchall()
        creations=connection.execute('SELECT stage,expected_head,number FROM pr_creations LIMIT 2').fetchall()
    finally:connection.close()
    after=path.lstat()
    identity=lambda v:(v.st_dev,v.st_ino,v.st_uid,v.st_mode,v.st_size,v.st_mtime_ns,v.st_ctime_ns)
    if identity(before)!=identity(after):raise Stop('DB_CHANGED')
    if len(runs)!=1 or len(events)>32 or len(failures)>1 or len(creations)>1:raise Stop('DB_BOUND')
    row=runs[0]
    expected_worktree='/state/queue/'+QUEUE+'/bridge/worktrees/'+RUN
    if row[0]!=RUN or row[2:6]!=(AUTH,PIN,'issue43-one-shot-review-note',expected_worktree):raise Stop('RUN_IDENTITY')
    result={'status':enum(row[1],STATUS),'head':head(row[6]),'pr_recorded':row[7] is not None,
        'stages':[enum(e[0],STAGES) for e in events]}
    if failures:
        f=failures[0];result['failure']=dict(stage=enum(f[0],STAGES),category=enum(f[1],CATEGORIES),
            exit_code=number(f[2]),signal=number(f[3]),duration_ms=number(f[4]),stop_reason=enum(f[5],STOPS))
    else:result['failure']=None
    completions=[e for e in events if e[0]=='child_completion']
    if completions:
        e=completions[-1];result['child_completion']=dict(duration_ms=number(e[1]),exit_code=number(e[2]),signal=number(e[3]),stop_reason=enum(e[4],STOPS))
    if creations:
        c=creations[0];result['pr_creation']=dict(stage=enum(c[0],{'intent','responded','verified','reused'}),head=head(c[1]),number=number(c[2]))
    return result,expected_worktree


def inspect(workspace):
    if os.geteuid()!=0:raise Stop('ROOT_REQUIRED')
    w=Path(workspace)
    if not w.is_absolute() or str(w)!=workspace or '..' in w.parts:raise Stop('WORKSPACE_PATH')
    directory(w,0)
    plan=json.loads(read_bytes(w/(ATTEMPT+'-runtime-v2-plan.json'),0))
    expected=dict(state=str(w/(ATTEMPT+'-state')),bundle=str(w/(ATTEMPT+'-runtime-v2-bundle')),
        signer_token=str(w/'root-github-token'),journal_parent=str(w/(ATTEMPT+'-journal_parent')),
        merge='42db985bba2f0a64ce8d848e39a11c2a18c689f3',uid=10000,gid=10000,attempt=ATTEMPT)
    if any(plan.get(k)!=v for k,v in expected.items()):raise Stop('PLAN_SCOPE')
    parent=Path(plan['journal_parent'])/(ATTEMPT+'-issue43-once');directory(parent,0)
    lifecycle=json.loads(read_bytes(parent/'phase.json',0))
    if lifecycle.get('attempt')!=ATTEMPT:raise Stop('ATTEMPT_IDENTITY')
    queue_root=Path(plan['state'])/'queue'/QUEUE;directory(queue_root,10000)
    queue=json.loads(read_bytes(queue_root/'state.json',10000))
    if queue.get('id')!=QUEUE or queue.get('bridge_run_id')!=RUN or queue.get('authorization_identity')!=AUTH:
        raise Stop('QUEUE_IDENTITY')
    diagnostic,worktree=database(queue_root/'bridge'/'journal.sqlite3')
    config=json.loads(read_bytes(parent/'compose.issue43-once.json',0,65536))
    safe=config.get('services',{}).get('inbox-worker',{}).get('environment',{}).get('HERMES_WRITE_SAFE_ROOT')
    # Publish only containment, never host paths/environment or raw failure text.
    roots=safe.split(':') if isinstance(safe,str) else []
    contains=any(worktree==r or worktree.startswith(r.rstrip('/')+'/') for r in roots if r.startswith('/'))
    result=dict(diagnostic='issue43-blocked-v1',queue_id=QUEUE,run_id=RUN,grant_id=6777657372,
        lifecycle=dict(phase=enum(lifecycle.get('phase'),PHASES),status=enum(lifecycle.get('status'),STATUS),
            intent=enum(lifecycle.get('intent'),PHASES) if lifecycle.get('intent') is not None else None,
            unresolved=enum(lifecycle.get('unresolved_effect'),PHASES) if lifecycle.get('unresolved_effect') is not None else None,
            cleanup_verified=lifecycle.get('cleanup_verified') is True),
        queue=dict(status=enum(queue.get('status'),STATUS),invocations=number(queue.get('invocations')),
            failure_code=enum(queue.get('failure_code'),{'preflight','ambiguous','bridge-blocked','bridge'})),
        bridge=diagnostic,write_root_contains_worktree=contains,runtime_state='UNVERIFIED_PRESERVE',retry=False,timer=False)
    checkpoint=queue_root/'bridge'/'recovery-checkpoint.json'
    if os.path.lexists(checkpoint):
        c=json.loads(read_bytes(checkpoint,10000,4096))
        if c.get('identity',{}).get('run_id')!=RUN:raise Stop('CHECKPOINT_IDENTITY')
        result['checkpoint']=dict(stage=enum(c.get('stage'),CHECKPOINTS),last_confirmed=enum(c.get('last_confirmed'),CHECKPOINTS),head=head(c.get('head')))
    text=json.dumps(result,sort_keys=True,separators=(',',':'))
    if len(text.encode())>2048:raise Stop('REPORT_BOUND')
    return w,plan,text


def fresh_json(path,data):
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as f:json.dump(data,f,sort_keys=True);f.flush();os.fsync(f.fileno())
    fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)


def report(w,plan,text,client=None):
    marker=w/(ATTEMPT+'-issue43-diagnostic-report')
    # A consumed intent is a read-only reconciliation boundary, even if GET/POST fails.
    fresh_json(marker,dict(schema=1,status='post-intent',body_sha256=hashlib.sha256(text.encode()).hexdigest()))
    if client is None:
        directory(Path(plan['bundle']),0)
        data=read_bytes(Path(plan['bundle'])/'root_signer.py',0,65536)
        if hashlib.sha256(data).hexdigest()!=SIGNER_SHA:raise Stop('REPORT_CLIENT_DIGEST')
        module=types.ModuleType('_protected_diagnostic_reporter');sys.modules[module.__name__]=module
        exec(compile(data,'<reviewed-root-signer>','exec'),module.__dict__)
        client=module.GitHub(Path(plan['signer_token']),deadline=time.monotonic()+90)
    ident=client.publish(41,text)
    row=client.comment(41,ident)
    if row.get('id')!=ident or row.get('body')!=text or row.get('issue_url')!='https://api.github.com/repos/aliercankonus/signal-desk-prediction/issues/41':
        raise Stop('REPORT_READBACK')
    fresh_json(Path(str(marker)+'-receipt'),dict(id=ident,verified=True,body_sha256=hashlib.sha256(text.encode()).hexdigest()))
    return ident


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace',required=True);parser.add_argument('--report',action='store_true');args=parser.parse_args()
    try:
        w,plan,text=inspect(args.workspace)
        if args.report:print('GITHUB_DIAGNOSTIC_REPORT: '+str(report(w,plan,text)))
        else:print(text)
        print('HOST_RUNTIME: PRESERVED; no Docker, Git, cleanup, model or task action')
        return 0
    except Exception as exc:
        code=str(exc) if isinstance(exc,Stop) and re.fullmatch('[A-Z0-9_]{1,80}',str(exc)) else 'UNVERIFIED_PRESERVE'
        print('STOP: DIAGNOSTIC '+code+'; preserve state; no retry or cleanup');return 1

if __name__=='__main__':raise SystemExit(main())
