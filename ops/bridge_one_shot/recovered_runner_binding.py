"""Dormant recovered-runner binding gate. No CLI, writes or lifecycle execution.

Call only from a later reviewed root adapter with independently hash-verified
host/recovery/a2 modules and authenticated GitHub client. Returned plan is a
proposal, never authority; the frozen lifecycle must still preflight the worker.
"""
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import re
import stat

REPO='aliercankonus/signal-desk-prediction'
PIN='e84021a786004456a12de9e25eae50d191da6cf1'
AUTH='1da74bf1d715dc3c0a78809955a2401744e85f64014bdbb57a1e9626e001c037'
INSTRUCTION=6824067293
RECEIPT=6825239944
ATTEMPT='issue43-a2-20261112'
RECOVERY='object-clone-recovery-02'
OLD='issue41-cold-20261110-01'

class Blocked(ValueError):pass


def expected_report():
    return dict(preparation='a2-object-clone-recovery-v2',pin=PIN,prepared_runner=True,old_prefix_preserved=True,
        source_refs_unchanged=True,retry=False,runtime=False,signing=False,task=False,timer=False)


def detached_head(runner,uid=10000):
    path=runner/'.git'/'HEAD'
    for parent in (path.parent,*path.parent.parents):
        info=parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid not in (0,uid) or info.st_mode&0o022:raise Blocked('HEAD_ANCESTRY')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=uid or info.st_nlink!=1 or info.st_mode&0o022 or info.st_size!=41:raise Blocked('HEAD_METADATA')
        data=os.read(fd,42);after=os.fstat(fd);named=path.lstat()
        key=lambda v:(v.st_dev,v.st_ino,v.st_mode,v.st_uid,v.st_size,v.st_mtime_ns,v.st_ctime_ns,v.st_nlink)
        if key(info)!=key(after) or key(info)!=key(named) or len(data)!=41:raise Blocked('HEAD_CHANGED')
        return data
    finally:os.close(fd)


def bind(workspace,old,*,host,recovery,a2,client,uid=10000,gid=10000):
    """Read-only validation; no root Git against the worker-owned checkout.

    Dependencies are explicit protected-code seams, never imported from worker
    paths. There is deliberately no production entry or automatic continuation.
    """
    w=Path(workspace)
    if not w.is_absolute() or '..' in w.parts:raise Blocked('WORKSPACE')
    recovery.private_dir(w);root=w/ATTEMPT;recovery.private_dir(root)
    rec=root/RECOVERY;recovery.private_dir(rec)
    if old.attempt!=OLD or (old.uid,old.gid)!=(uid,gid):raise Blocked('OLD_PLAN')
    recorded=json.loads(recovery.blob(w/(OLD+'-runtime-v2-plan.json')))
    actual={f.name:str(getattr(old,f.name)) if isinstance(getattr(old,f.name),Path) else getattr(old,f.name) for f in host.fields(host.Plan)}
    if recorded!=actual:raise Blocked('OLD_PLAN_CHANGED')
    original=json.loads(recovery.blob(w/(OLD+'-bootstrap-spec.json')))
    expected={f.name:original[f.name] for f in host.fields(host.Plan)}
    expected.update({k:str(w/(OLD+'-runtime-v2-'+k)) for k in ('bundle','auth','home')})
    expected['merge']='42db985bba2f0a64ce8d848e39a11c2a18c689f3'
    if recorded!=expected:raise Blocked('OLD_TRANSITION')
    if {p.name for p in rec.iterdir()}!={'intent.json','runner','ready.json','report-intent.json','report-receipt.json'}:raise Blocked('RECOVERY_INVENTORY')
    for name in ('plan.json','stage-ready.json','runtime.json'):
        if os.path.lexists(root/name):raise Blocked('ADVANCED_STAGE')
    for folder in (root/'journals',root/'state'/'queue'):
        host.trusted_worker_mount(folder,uid)
        if any(folder.iterdir()):raise Blocked('NONEMPTY_RUNTIME')
    if os.path.lexists(root/'state'/'github-inbox') or os.path.lexists(old.signer_state_root/str(INSTRUCTION)):raise Blocked('CLAIM_PRESENT')
    ready=json.loads(recovery.blob(rec/'ready.json'));intent=json.loads(recovery.blob(rec/'intent.json'))
    if set(ready)!={'schema','pin','source_refs_unchanged','old_prefix_sha256','source_state','prepared_runner','task','runtime','signing','timer'}:raise Blocked('READY_SCHEMA')
    if (ready.get('schema')!=1 or ready.get('pin')!=PIN or ready.get('source_refs_unchanged') is not True or
        ready.get('prepared_runner') is not True or any(ready.get(k) is not False for k in ('task','runtime','signing','timer'))):raise Blocked('READY_SCOPE')
    digest=ready.get('old_prefix_sha256')
    if not isinstance(digest,str) or not re.fullmatch('[0-9a-f]{64}',digest):raise Blocked('PREFIX_DIGEST')
    if intent!=dict(schema=1,pin=PIN,old_prefix_sha256=digest,task=False,runtime=False):raise Blocked('RECOVERY_INTENT')
    if recovery.snapshot(root)!=digest or recovery.refs(old.source)!=ready['source_state']:raise Blocked('PRESERVATION_CHANGED')
    report=json.dumps(expected_report(),sort_keys=True,separators=(',',':'))
    if json.loads(recovery.blob(rec/'report-intent.json'))!={'body_sha256':hashlib.sha256(report.encode()).hexdigest()}:raise Blocked('REPORT_INTENT')
    if json.loads(recovery.blob(rec/'report-receipt.json'))!={'id':RECEIPT,'verified':True}:raise Blocked('REPORT_RECEIPT')
    row=client.comment(41,RECEIPT)
    if (row.get('id')!=RECEIPT or row.get('issue_url')!='https://api.github.com/repos/'+REPO+'/issues/41' or
        row.get('body')!=report or row.get('user',{}).get('id')!=35579049 or row.get('created_at')!=row.get('updated_at')):raise Blocked('REMOTE_RECEIPT')
    instruction=a2.instruction(client,INSTRUCTION)
    task=client.task(43)
    if task.get('state')!='open' or hashlib.sha256(task['body'].encode()).hexdigest()!=a2.DIGEST:raise Blocked('TASK_CHANGED')
    if json.loads(recovery.blob(root/'stage-intent.json'))!=dict(instruction_id=INSTRUCTION,policy=a2.POLICY,retry=False):raise Blocked('STAGE_INTENT')
    runner=rec/'runner';host.trusted_worker_mount(runner,uid)
    if (runner.lstat().st_uid,runner.lstat().st_gid)!=(uid,gid):raise Blocked('RUNNER_OWNER')
    # Root only reads detached HEAD bytes; all Git/context execution must occur
    # later as the reviewed worker, with the frozen ownership checks intact.
    head=detached_head(runner,uid)
    if head!=PIN.encode()+b'\n':raise Blocked('RUNNER_HEAD')
    plan=replace(old,attempt=ATTEMPT,runner=runner,state=root/'state',auth=root/'auth',inbox=root/'inbox',
        signer_policy=root/'signer-policy.json',journal_parent=root/'journals')
    scope_data=json.loads(recovery.blob(plan.signer_policy))
    expected_scope=dict(repo=REPO,task_issue=43,body_digest=a2.DIGEST,authority_identity=AUTH,runner_commit=PIN,start=instruction['created_at'],cursors={'41':INSTRUCTION-1,'45':6713729283},app_id=1144995)
    if scope_data!=expected_scope:raise Blocked('SCOPE_CHANGED')
    # a2.binding checks exact policy/enrollment/public-key mapping without signing.
    from types import SimpleNamespace
    a2.binding(plan,SimpleNamespace(**scope_data),host,recovery)
    return plan
