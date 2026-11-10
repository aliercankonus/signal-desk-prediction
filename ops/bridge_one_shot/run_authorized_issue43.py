"""Operator-only single approved #43 attempt. No timer, retry or device login.

A flag is not task authority. The exact instruction identity below is backed by
Ali's explicit approval in the manager conversation, recorded in #41.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import stat
import sys
import time
import types

ATTEMPT = 'issue41-cold-20261110-01'
TASK_JOURNAL = ATTEMPT+'-issue43-once'
AUTH_HELPER_SHA256 = '405e3a9ce73cf22403ea9d75a976df920cc99c1517b057749caa9681434f4b84'
INSTRUCTION_ID = 6775497757
INSTRUCTION_TIME = '2026-11-10T18:17:42Z'
AUTHORITY = '2cc0a42be444e93491b14f37bd9fdbd0c71e65d30305d7b79c24b32c94c59cfa'
BODY = 'RUN FROZEN DEVELOPMENT TASK #43 AUTH '+AUTHORITY
CURSORS = {'41':6761280723,'45':6713729283}

class Stop(Exception): pass


def auth_module(path):
    # Never import a worker checkout or arbitrary sibling module as root.
    path=Path(path)
    for p in (path.parent,*path.parent.parents):
        s=p.lstat()
        if not stat.S_ISDIR(s.st_mode) or s.st_uid!=0 or s.st_mode&0o022:raise Stop('HELPER_ANCESTRY')
    s=path.lstat()
    if not stat.S_ISREG(s.st_mode) or s.st_uid!=0 or s.st_nlink!=1 or s.st_mode&0o077 or s.st_size>65536:
        raise Stop('HELPER_METADATA')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as f:
        opened=os.fstat(f.fileno());data=f.read(65537)
    identity=lambda x:(x.st_dev,x.st_ino,x.st_mode,x.st_uid,x.st_size,x.st_mtime_ns,x.st_nlink)
    if not identity(s)==identity(opened)==identity(path.lstat()) or hashlib.sha256(data).hexdigest()!=AUTH_HELPER_SHA256:
        raise Stop('HELPER_DIGEST')
    module=types.ModuleType('_reviewed_successful_auth')
    exec(compile(data,'<reviewed-auth-helper>','exec'),module.__dict__)
    return module


def history(plan,auth):
    first=plan.journal_parent/(ATTEMPT+'-auth-only-01')
    second=plan.journal_parent/auth.CORRECTED_JOURNAL
    if {p.name for p in plan.journal_parent.iterdir()}!={first.name,second.name}:raise Stop('HISTORY_PRESERVE')
    for p in (first,second):auth.root_dir(p)
    if {p.name for p in first.iterdir()}!={'phase.json','compose.auth-only.json','auth-only-receipt.json'}:
        raise Stop('OLD_HISTORY_INVENTORY')
    auth.failure_records(json.loads(auth.blob(first/'auth-only-receipt.json')),json.loads(auth.blob(first/'phase.json')))
    if {p.name for p in second.iterdir()}!={'phase.json','compose.auth-only.json','auth-only-receipt.json','worker_preflight_v3.py'}:
        raise Stop('SUCCESS_HISTORY_INVENTORY')
    receipt=json.loads(auth.blob(second/'auth-only-receipt.json'))
    expected=dict(schema=1,github_readonly_verified=True,device_cli_success=True,cleanup_verified=True,
        partial_startup=False,failure=None,failure_phase=None,worker_preflight_code=None,child_exit_code=None,
        enrollment=False,signing=False,dispatch=False,timer=False,model_entitlement='UNPROVEN',manager_exclusivity='UNPROVEN')
    phase=json.loads(auth.blob(second/'phase.json'))
    if receipt!=expected:raise Stop('SUCCESS_RECEIPT_REQUIRED')
    if phase!=dict(version=1,attempt=ATTEMPT,phase='cleanup',status='pending',intent=None,
        unresolved_effect=None,owned=[],cleanup_verified=True,report_receipt=None):raise Stop('AUTH_CLEANUP_UNVERIFIED')
    if auth.blob(second/'worker_preflight_v3.py',mode=0o444)!=auth.WORKER_PREFLIGHT_V3:
        raise Stop('OWNER_OVERLAY_DIGEST')


def load(workspace, auth):
    root_dir, blob, protected_module = auth.root_dir, auth.blob, auth.protected_module
    RELEASE, SOURCE, RUNNER = auth.RELEASE, auth.SOURCE, auth.RUNNER
    if os.geteuid()!=0:raise Stop('ROOT_REQUIRED')
    w=Path(workspace)
    if not w.is_absolute() or str(w)!=workspace or '..' in w.parts:raise Stop('WORKSPACE_PATH')
    root_dir(w);bundle=w/(ATTEMPT+'-runtime-v2-bundle');root_dir(bundle)
    receipt=json.loads(blob(w/(ATTEMPT+'-runtime-v2-receipt.json')))
    if (receipt.get('schema')!=2 or receipt.get('source_commit')!=SOURCE or receipt.get('runner_commit')!=RUNNER or
        receipt.get('source_refs_preserved') is not True or receipt.get('original_staging_preserved') is not True or
        receipt.get('worker_credential_installed') is not True or receipt.get('provider_authentication') is not False or
        receipt.get('activation') is not False or receipt.get('runtime_authority') is not False or receipt.get('task_authority') is not False):
        raise Stop('V2_RECEIPT_SCOPE')
    exposed={'worker_probe.py','connect_proxy.py','worker_credential.py','worker_preflight.py'}
    expected={Path(p).name for p in RELEASE}|{'merged-byte-manifest.json'}
    if {p.name for p in bundle.iterdir()}!=expected:raise Stop('BUNDLE_INVENTORY')
    for name,digest in RELEASE.items():
        data=blob(bundle/Path(name).name,mode=0o444 if Path(name).name in exposed else 0o600)
        if hashlib.sha256(data).hexdigest()!=digest:raise Stop('BUNDLE_DIGEST')
    if json.loads(blob(bundle/'merged-byte-manifest.json'))!={'schema':1,'merge':SOURCE,'sha256':RELEASE}:
        raise Stop('BUNDLE_MANIFEST')
    # Import only root-protected, digest-verified public code. No key/token store
    # is opened by these imports; no root signer, grant or report method is used.
    # The frozen adapter inserts sibling search paths. Pin its two project imports
    # explicitly so an unrelated sibling directory cannot shadow verified code.
    for name in ('operator_lifecycle','root_signer'):protected_module(name,bundle/(name+'.py'))
    host=protected_module('_reviewed_auth_host',bundle/'operator_host_v2.py')
    plan=host.load_plan(w/(ATTEMPT+'-runtime-v2-plan.json'))
    original=json.loads(blob(w/(ATTEMPT+'-bootstrap-spec.json')))
    target={f.name:original[f.name] for f in host.fields(host.Plan)}
    target.update({k:str(w/(ATTEMPT+'-runtime-v2-'+k)) for k in ('bundle','auth','home')});target['merge']=SOURCE
    if json.loads(blob(w/(ATTEMPT+'-runtime-v2-plan.json')))!=target:raise Stop('PLAN_TRANSITION')
    for path in (plan.source,plan.journal_parent,plan.signer_state_root):root_dir(path)
    for path in (plan.runner,plan.state,plan.auth,plan.context,plan.home,plan.venv,plan.inbox):
        host.trusted_worker_mount(path,10000)
        s=path.lstat()
        if s.st_uid!=10000 or s.st_gid!=10000:raise Stop('WORKER_DIRECTORY_OWNER')
    if (plan.uid,plan.gid)!=(10000,10000):raise Stop('WORKER_IDENTITY')
    if {p.name for p in plan.auth.iterdir()}!={'authorization.json','github-token'}:
        raise Stop('PRIOR_AUTH_STATE_PRESERVE')
    helper=types.ModuleType('_reviewed_auth_credential')
    exec(compile(blob(bundle/'worker_credential.py',mode=0o444),'<reviewed-helper>','exec'),helper.__dict__)
    if host.worker_private_bytes(plan.home/'gitconfig',10000)!=helper.GITCONFIG.encode():raise Stop('GIT_CONFIG')
    s=(plan.auth/'github-token').lstat()  # Metadata only; credential consumed only by worker Git.
    if not stat.S_ISREG(s.st_mode) or (s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode),s.st_nlink)!=(10000,10000,0o400,1):
        raise Stop('WORKER_CREDENTIAL_METADATA')
    for path in (plan.state/'queue',plan.signer_state_root):
        if path.is_symlink() or not path.is_dir() or any(path.iterdir()):raise Stop('EXISTING_RUNTIME_STATE')
    if os.path.lexists(plan.state/'github-inbox'):raise Stop('EXISTING_JOURNAL_INBOX')
    history(plan, auth)
    return host,plan



def exact_instruction(row):
    if (not isinstance(row,dict) or row.get('id')!=INSTRUCTION_ID or row.get('body')!=BODY or
        row.get('issue_url')!='https://api.github.com/repos/aliercankonus/signal-desk-prediction/issues/41' or
        row.get('created_at')!=INSTRUCTION_TIME or row.get('updated_at')!=INSTRUCTION_TIME or
        (row.get('user') or {}).get('id')!=35579049 or
        (row.get('performed_via_github_app') or {}).get('id')!=1144995):raise Stop('EXACT_APPROVED_INSTRUCTION_CHANGED')
    return row


class PinnedSigner:
    def __init__(self,client):self.client=client
    def task(self,issue):return self.client.task(issue)
    def publish(self,issue,body):return self.client.publish(issue,body)
    def comment(self,issue,ident):
        row=self.client.comment(issue,ident)
        if ident==INSTRUCTION_ID:
            if issue!=41:raise Stop('INSTRUCTION_ISSUE')
            exact_instruction(row)
        return row


# Runs only as UID 10000 inside the verified worker. The frozen implementation
# still owns private enrollment validation, signature verification, queue locking,
# no-replay claims, receipts, actual Bridge dispatch and publication.
WORKER = r'''
import json,sys,os
from pathlib import Path
sys.path[:0]=['/workspace/runner/src','/workspace/runner/autonomous-development']
from github_inbox import GitHub,Inbox,load_enrollment,production_executor
from signal_desk.task_bridge.adapters import HermesAgent
args=json.loads(sys.argv[1])
action=args['action']
if action=='preflight':
    gate='TASK_ENVIRONMENT'
    try:
        if os.environ.get('HERMES_WRITE_SAFE_ROOT')!='/state/worktrees':raise ValueError()
        gate='TASK_ENROLLMENT_CONTEXT'
        cfg,policy,key=load_enrollment('/private/inbox/enrollment.json')
        agent=HermesAgent(cfg['runner'],cfg['queue'],policy,context_path=cfg['context'])
        gate='TASK_CLI_FLAGS';agent.check()
        gate='TASK_CONTEXT_OR_GIT';agent.preflight()
    except Exception:
        print(json.dumps({'task_preflight':False,'gate':gate}));raise SystemExit(0)
    print(json.dumps({'task_preflight':True}));raise SystemExit(0)
class ExactFeed:
    def __init__(self):self.client=None
    def remote(self):
        if self.client is None:self.client=GitHub()
        return self.client
    def latest(self,issue):return args['cursors'][str(issue)]
    def comments(self,issue,since,etag=None):
        if issue==41:yield self.comment(41,args['grant_id']),None
    def comment(self,issue,ident):
        if issue!=41 or ident not in (args['instruction_id'],args['grant_id']):raise ValueError('exact feed scope')
        return self.remote().comment(issue,ident)
    def publish(self,issue,text):return self.remote().publish(issue,text)
inbox=Inbox('/private/inbox/enrollment.json',Path('/state/github-inbox'),
            ExactFeed() if action in ('enroll','tick') else None,production_executor)
if action=='enroll':inbox.enroll(args['start']);result=inbox.doctor()
elif action=='doctor':result=inbox.doctor()
elif action=='enable':inbox.enable();result=inbox.doctor()
elif action=='disable':inbox.disable();result=inbox.doctor()
elif action=='tick':result=inbox.tick()
else:raise ValueError('one task action')
print(json.dumps(result,sort_keys=True))
'''


def task_mounts(auth,plan,service):
    result=auth._original_mounts(plan,service)
    return {k:(rw or service=='inbox-worker' and k[0] in ('/workspace/runner','/state')) for k,rw in result.items()}


def prepare(journal,ops,host,auth):
    original_preflight=ops.preflight
    def preflight():
        # Verify original protected source/plan/signing binding before resources.
        original_preflight();auth.preflight(ops,host)
        from root_signer import GitHub,load_scope
        scope=load_scope(ops.plan.signer_policy)
        if scope.authority_identity!=AUTHORITY or scope.cursors!=CURSORS:
            raise Stop('FROZEN_SCOPE')
        ops.signer=PinnedSigner(GitHub(ops.plan.signer_token,deadline=ops.deadline-420))
        exact_instruction(ops.signer.comment(41,INSTRUCTION_ID))
        rendered=json.loads(ops._compose('config','--format','json'))
        config=auth.auth_config(rendered,ops.plan)
        config['services']['inbox-worker']['environment']['HERMES_WRITE_SAFE_ROOT']='/state/worktrees'
        config_path=journal.directory/'compose.issue43-once.json'
        fd=os.open(config_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as f:json.dump(config,f);f.flush();os.fsync(f.fileno())
        parent=os.open(journal.directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:os.fsync(parent)
        finally:os.close(parent)
        auth.configure(ops,config_path)
    def worker(action,**kw):
        args=dict(action=action,instruction_id=INSTRUCTION_ID,cursors=CURSORS,
                  start=kw.pop('start',None),grant_id=kw.pop('grant_id',None))
        value=ops._worker('/opt/hermes/.venv/bin/python','-I','-B','-c',WORKER,
                          json.dumps(args,separators=(',',':')),timeout=kw.pop('timeout',60))
        return json.loads(value)
    def login():
        # Reuse auth; never run auth add/login, copy stores or prompt device flow.
        result=json.loads(ops._worker('/opt/hermes/.venv/bin/python','-I','-B','/opt/worker-preflight.py',timeout=35))
        if result!={'worker_owner_git':True,'credential_helper_configured':True}:raise Stop('OWNER_CONFIG')
        result=worker('preflight',timeout=120)
        if result!={'task_preflight':True}:
            gate=result.get('gate')
            raise Stop(gate if gate in ('TASK_ENVIRONMENT','TASK_ENROLLMENT_CONTEXT','TASK_CLI_FLAGS','TASK_CONTEXT_OR_GIT') else 'TASK_PREFLIGHT')
    def inbox(action,*extra,timeout=30):
        if action=='enroll':
            if len(extra)!=2 or extra[0]!='--start':raise Stop('ENROLL_ARGUMENTS')
            return worker(action,start=extra[1],timeout=timeout)
        if action=='tick':
            if type(ops.approved_grant) is not int:raise Stop('EXACT_GRANT_REQUIRED')
            try:return worker(action,grant_id=ops.approved_grant,timeout=timeout)
            except BaseException:
                try:ops._stop_claim_runtime()
                except BaseException:ops.runtime_stopped=False
                raise
        if action not in ('doctor','enable','disable') or extra:raise Stop('INBOX_ACTION')
        return worker(action,timeout=timeout)
    def claim():
        from root_signer import load_scope,sign_once,openssl_sign,openssl_verify
        if str((ops.plan.state/'github-inbox').lstat().st_ino)!=ops.enrollment_inode:raise Stop('ENROLLMENT_CHANGED')
        scope=load_scope(ops.plan.signer_policy)
        if ops.deadline-time.monotonic()-420<840:raise Stop('TASK_TIME_RESERVE')
        deadline=ops.deadline-540
        # Exactly one sign attempt for exactly one approved immutable comment.
        grant=sign_once(scope,ops.plan.signer_state_root,ops.signer,41,INSTRUCTION_ID,
            lambda payload,*,deadline:openssl_sign(ops.plan.signer_key,payload,deadline=deadline),
            verify=lambda payload,sig,*,deadline:openssl_verify(ops.plan.signer_public,payload,sig,deadline=deadline),deadline=deadline)
        if grant.get('status')!='verified' or type(grant.get('grant_id')) is not int:raise Stop('GRANT_UNVERIFIED')
        ops.approved_grant=grant['grant_id']
        available=ops.deadline-time.monotonic()-420
        if available<720:raise Stop('TASK_TIME_RESERVE')
        result=inbox('tick',timeout=min(3600,available));ops.claim_status=result
        if result.get('status')!='review-ready':raise Stop('TASK_BLOCKED_PRESERVE')
        return ()
    ops.preflight=preflight;ops.login=login;ops._inbox=inbox;ops.one_bridge_claim=claim
    ops.approved_grant=None
    ops.failure_stage=None;ops.failure_code=None
    for phase in ('preflight','start_isolation','login','github_reads','enroll_disabled','enable_inbox','one_bridge_claim','reconcile','cleanup'):
        original=getattr(ops,phase)
        def diagnostic(*args,_phase=phase,_original=original,**kwargs):
            try:return _original(*args,**kwargs)
            except (Exception,KeyboardInterrupt) as exc:
                if ops.failure_stage is None:
                    ops.failure_stage=_phase.upper()
                    ops.failure_code=str(exc) if isinstance(exc,Stop) and re.fullmatch('[A-Z0-9_]{1,80}',str(exc)) else type(exc).__name__
                raise
        setattr(ops,phase,diagnostic)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace',required=True);parser.add_argument('--auth-helper',required=True)
    parser.add_argument('--execute-approved-issue43',action='store_true')
    args=parser.parse_args()
    previous=signal.getsignal(signal.SIGTERM)
    def interrupted(*_):raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM,interrupted)
    try:
        auth=auth_module(args.auth_helper);host,plan=load(args.workspace,auth)
        if not args.execute_approved_issue43:
            print('ISSUE43: REVIEWED_FILES_ONLY; no runtime or credential action');return 0
        if not sys.stdin.isatty():raise Stop('LIVE_OPERATOR_TTY_REQUIRED')
        auth._original_mounts=auth.mounts
        auth.mounts=lambda p,s:task_mounts(auth,p,s)
        deadline=time.monotonic()+plan.overall_seconds
        if plan.overall_seconds<1800:raise Stop('TASK_TIME_BUDGET')
        journal=host.Journal(plan.journal_parent/TASK_JOURNAL,plan.attempt)
        ops=host.HostOperations(plan,runner=host.CommandRunner(deadline=deadline),deadline=deadline)
        prepare(journal,ops,host,auth)
        result=host.run_once(journal,ops,deadline=deadline)
        print('ISSUE43: '+('REVIEW_READY' if result['status']=='review-ready' else 'BLOCKED_PRESERVE_STATE'))
        print('OWN_RUNTIME_CLEANUP: '+('EXACT_IDS_VERIFIED' if result['cleanup_verified'] else 'UNVERIFIED_PRESERVE'))
        print('GITHUB_REPORT: '+(result['report_receipt'] or 'UNVERIFIED_PRESERVE'))
        if getattr(ops,'failure_stage',None):print('TASK_FAILURE: '+ops.failure_stage+' '+ops.failure_code)
        print('HOURLY_TIMER: NOT_INSTALLED')
        return 0 if result['status']=='review-ready' and result['cleanup_verified'] else 2
    except (Exception,KeyboardInterrupt) as exc:
        code=str(exc) if isinstance(exc,Stop) and re.fullmatch('[A-Z0-9_]{1,80}',str(exc)) else 'PRESERVE_STATE'
        print('STOP: ISSUE43 '+code+'; preserve files/resources; no retry or guessed cleanup');return 1
    finally:signal.signal(signal.SIGTERM,previous)

if __name__=='__main__':raise SystemExit(main())
