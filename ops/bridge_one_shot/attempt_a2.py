"""Preparation-only source for one NEW explicitly approved #43 attempt.

Default review performs no host/network/credential/task action. The manager must
obtain new bounded conversation approval before publishing an exact RUN and
supplying the operator command. A flag/issue comment is not that authority.
"""
from dataclasses import replace
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import time
import types
import urllib.request

REPO='aliercankonus/signal-desk-prediction'
OLD='issue41-cold-20261110-01'
ATTEMPT='issue43-a2-20261112'
PIN='e84021a786004456a12de9e25eae50d191da6cf1'
BRANCH='issue43-one-shot-a2'
DIGEST='c9e4e393ccc506954f0a18e6eaeea7c82ff598b0b41eac642d7f88da1fca73c6'
POLICY=dict(repo=REPO,issue=43,body_digest=DIGEST,base=PIN,branch=BRANCH)
AUTHORITY=hashlib.sha256(json.dumps(POLICY,sort_keys=True,separators=(',',':')).encode()).hexdigest()
FILES={'auth':'ops/bridge_one_shot/authenticate_worker_clone_fix.py',
 'write_root':'ops/github_inbox/queued_write_root.py',
 'cleanup':'ops/bridge_one_shot/cleanup_consumed_issue43.py',
 'diag':'ops/bridge_one_shot/inspect_blocked_issue43.py',
 'signer':'ops/github_inbox/root_signer_a2.py',
 'readback':'ops/bridge_one_shot/bridge_readback_a2.py',
 'capture':'ops/github_inbox/child_capture_a2.py','factory':'ops/github_inbox/factory_a2.py'}

class Stop(Exception):pass

def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':')).encode()

def fetch(commit,path):
    if not re.fullmatch('[0-9a-f]{40}',commit) or path not in set(FILES.values())|{'ops/bridge_one_shot/release_a2.json'}:raise Stop('RELEASE_INPUT')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*a,**k):raise Stop('RELEASE_REDIRECT')
    if signal.getitimer(signal.ITIMER_REAL)[0]:raise Stop('EXISTING_TIMER')
    old=signal.getsignal(signal.SIGALRM)
    def timeout(*_):raise TimeoutError()
    signal.signal(signal.SIGALRM,timeout);signal.alarm(20)
    try:
        with urllib.request.build_opener(NoRedirect).open('https://raw.githubusercontent.com/'+REPO+'/'+commit+'/'+path,timeout=15) as r:data=r.read(65537)
    finally:signal.alarm(0);signal.signal(signal.SIGALRM,old)
    if not data or len(data)>65536:raise Stop('RELEASE_BOUND')
    return data

def release(commit,digest,get=fetch):
    raw=get(commit,'ops/bridge_one_shot/release_a2.json')
    if hashlib.sha256(raw).hexdigest()!=digest:raise Stop('RELEASE_MANIFEST_DIGEST')
    manifest=json.loads(raw)
    if set(manifest)!=set(FILES.values()) or any(not re.fullmatch('[0-9a-f]{64}',d) for d in manifest.values()):raise Stop('RELEASE_MANIFEST_SCOPE')
    blobs={}
    for name,path in FILES.items():
        data=get(commit,path)
        if hashlib.sha256(data).hexdigest()!=manifest[path]:raise Stop('RELEASE_FILE_DIGEST')
        blobs[name]=data
    return blobs

def module(name,data):
    result=types.ModuleType(name);sys.modules[name]=result
    exec(compile(data,'<reviewed-'+name+'>','exec'),result.__dict__)
    return result

def put(path,data,uid=0,gid=0,mode=0o600):
    if not isinstance(data,bytes):data=canonical(data)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode)
    with os.fdopen(fd,'wb') as f:f.write(data);os.fchown(f.fileno(),uid,gid);f.flush();os.fsync(f.fileno())
    fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)

def mkdir(path,uid=0,gid=0):
    os.mkdir(path,0o700);os.chown(path,uid,gid)
    fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)

def instruction(client,ident):
    if type(ident) is not int or ident<=6822780163:raise Stop('NEW_INSTRUCTION_REQUIRED')
    row=client.comment(41,ident)
    if (row.get('id')!=ident or row.get('issue_url')!='https://api.github.com/repos/'+REPO+'/issues/41' or
        row.get('body')!='RUN FROZEN DEVELOPMENT TASK #43 AUTH '+AUTHORITY or
        row.get('created_at')!=row.get('updated_at') or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ',row.get('created_at','')) or
        row.get('user',{}).get('id')!=35579049 or (row.get('performed_via_github_app') or {}).get('id')!=1144995):raise Stop('EXACT_INSTRUCTION')
    return row

def git(argv):
    env={'PATH':'/usr/bin:/bin','HOME':'/nonexistent','LC_ALL':'C','GIT_CONFIG_GLOBAL':'/dev/null',
        'GIT_CONFIG_NOSYSTEM':'1','GIT_TERMINAL_PROMPT':'0','GIT_NO_REPLACE_OBJECTS':'1','GIT_NO_LAZY_FETCH':'1'}
    return subprocess.run(['/usr/bin/git','--no-optional-locks','-c','core.hooksPath=/dev/null','-c','core.fsmonitor=false',*map(str,argv)],
        env=env,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=60,check=True).stdout

def clone(source,destination,*,pin=PIN,uid=10000,gid=10000,run=git):
    run(['clone','--no-local','--no-checkout','--no-hardlinks',source,destination])
    run(['-C',destination,'remote','set-url','origin','https://github.com/'+REPO+'.git'])
    run(['-C',destination,'config','user.name','Signal Desk Worker'])
    run(['-C',destination,'config','user.email','35579049+aliercankonus@users.noreply.github.com'])
    run(['-C',destination,'checkout','--detach',pin])
    if run(['-C',destination,'rev-parse','HEAD']).strip()!=pin.encode() or run(['-C',destination,'status','--porcelain=v1','--untracked-files=all']):raise Stop('NEW_RUNNER_GIT')
    # No root Git operation follows ownership transfer. Never safe.directory.
    for parent,dirs,files in os.walk(destination,followlinks=False):
        for name in dirs+files:
            p=Path(parent)/name
            if p.is_symlink():raise Stop('NEW_RUNNER_SYMLINK')
            os.chown(p,uid,gid)
        os.chown(parent,uid,gid)

def reused_inputs(old,host):
    # Reuse the existing credential by file bind, never by copying/reading it.
    # Validate the source before Docker can follow a changed/symlinked path.
    for path in (old.auth,old.home):host.trusted_worker_mount(path,old.uid)
    info=(old.auth/'github-token').lstat()
    if (not stat.S_ISREG(info.st_mode) or (info.st_uid,info.st_gid,stat.S_IMODE(info.st_mode),info.st_nlink)!=(old.uid,old.gid,0o400,1)):
        raise Stop('REUSED_TOKEN_METADATA')
    if host.worker_private_bytes(old.home/'config.yaml',old.uid)!=b'auth:\n  adopt_external_logins: false\n  codex_login_flow: device_code\n':
        raise Stop('REUSED_DEVICE_ONLY_CONFIG')


def stage(w,old,host,auth,signer,blobs,ident,*,clone_runner=clone):
    auth.root_dir(w)
    original=json.loads(auth.blob(w/(OLD+'-bootstrap-spec.json')))
    expected={f.name:original[f.name] for f in host.fields(host.Plan)}
    expected.update({k:str(w/(OLD+'-runtime-v2-'+k)) for k in ('bundle','auth','home')});expected['merge']=auth.SOURCE
    recorded=json.loads(auth.blob(w/(OLD+'-runtime-v2-plan.json')))
    actual={f.name:str(getattr(old,f.name)) if isinstance(getattr(old,f.name),Path) else getattr(old,f.name) for f in host.fields(host.Plan)}
    if recorded!=expected or actual!=expected or (old.uid,old.gid)!=(10000,10000):raise Stop('ORIGINAL_PLAN_TRANSITION')
    receipt=json.loads(auth.blob(w/(OLD+'-exact-cleanup-01')/'report-receipt.json'))
    if receipt!={'id':6822780163,'verified':True}:raise Stop('EXACT_CLEANUP_REQUIRED')
    completed=json.loads(auth.blob(w/(OLD+'-exact-cleanup-01')/'runtime-cleanup-verified.json'))
    if completed!=dict(containers_removed=2,networks_removed=2,scoped_firewall_removed=True):raise Stop('CLEANUP_RECORD')
    for name,digest in auth.RELEASE.items():
        local=old.bundle/Path(name).name
        mode=0o444 if local.name in ('worker_probe.py','connect_proxy.py','worker_credential.py','worker_preflight.py') else 0o600
        if hashlib.sha256(auth.blob(local,mode=mode)).hexdigest()!=digest:raise Stop('OLD_BUNDLE_DIGEST')
    reused_inputs(old,host)
    client=signer.GitHub(old.signer_token,deadline=time.monotonic()+120)
    row=instruction(client,ident);task=client.task(43)
    if task.get('state')!='open' or hashlib.sha256(task['body'].encode()).hexdigest()!=DIGEST:raise Stop('FROZEN_TASK')
    prefix='/repos/'+REPO
    if client.get(prefix+'/git/ref/heads/'+BRANCH)!={'missing':True} or client.get(prefix+'/pulls?state=all&head=aliercankonus%3A'+BRANCH+'&per_page=2')!=[]:raise Stop('NEW_BRANCH_OR_PR_EXISTS')
    cursors={'41':ident-1,'45':6713729283}
    scope=dict(repo=REPO,task_issue=43,body_digest=DIGEST,authority_identity=AUTHORITY,runner_commit=PIN,start=row['created_at'],cursors=cursors,app_id=1144995)
    root=w/ATTEMPT
    if os.path.lexists(root):raise Stop('FRESH_ATTEMPT_EXISTS_PRESERVE')
    mkdir(root);put(root/'stage-intent.json',dict(instruction_id=ident,policy=POLICY,retry=False))
    for name in ('helpers','journals'):mkdir(root/name)
    for name in ('state','auth','inbox'):mkdir(root/name,10000,10000)
    mkdir(root/'state'/'queue',10000,10000)
    for name,data in blobs.items():put(root/'helpers'/(name+'.py'),data,mode=0o444)
    put(root/'helpers'/'worker-preflight-v3.py',auth.WORKER_PREFLIGHT_V3,mode=0o444)
    put(root/'auth'/'authorization.json',POLICY,10000,10000)
    # Empty target only; the existing token is separately read-only bind-mounted.
    put(root/'auth'/'github-token',b'',10000,10000,0o400)
    public=auth.blob(old.signer_public,limit=8192)
    put(root/'inbox'/'manager-public.pem',public,10000,10000)
    enrollment=dict(repo=REPO,issues=[41,45],task_issue=43,runner='/workspace/runner',runner_commit=PIN,queue='/state/queue',
        authorization='/private/auth/authorization.json',context='/private/context/context.json',public_key='/private/inbox/manager-public.pem',
        public_key_sha256=hashlib.sha256(public).hexdigest(),interval_seconds=300)
    put(root/'inbox'/'enrollment.json',enrollment,10000,10000)
    put(root/'signer-policy.json',scope)
    clone_runner(old.source,root/'runner')
    plan=replace(old,attempt=ATTEMPT,runner=root/'runner',state=root/'state',auth=root/'auth',inbox=root/'inbox',
        signer_policy=root/'signer-policy.json',journal_parent=root/'journals')
    put(root/'plan.json',{field.name:str(getattr(plan,field.name)) if isinstance(getattr(plan,field.name),Path) else getattr(plan,field.name) for field in host.fields(host.Plan)})
    put(root/'stage-ready.json',dict(schema=1,instruction_id=ident,root=ATTEMPT,policy_identity=AUTHORITY,activation=False))
    return root,plan,row,scope


def binding(plan,scope,host,auth):
    if (plan.uid,plan.gid)!=(10000,10000):raise Stop('WORKER_IDENTITY')
    if json.loads(host.worker_private_bytes(plan.auth/'authorization.json',10000))!=POLICY or scope.authority_identity!=AUTHORITY or scope.runner_commit!=PIN:raise Stop('A2_AUTHORITY_BINDING')
    cfg=json.loads(host.worker_private_bytes(plan.inbox/'enrollment.json',10000))
    public=auth.blob(plan.signer_public,limit=8192)
    if (set(cfg)!={'repo','issues','task_issue','runner','runner_commit','queue','authorization','context','public_key','public_key_sha256','interval_seconds'} or cfg.get('interval_seconds')!=300 or cfg.get('repo')!=REPO or cfg.get('issues')!=[41,45] or cfg.get('task_issue')!=43 or cfg.get('runner_commit')!=PIN or
        cfg.get('runner')!='/workspace/runner' or cfg.get('queue')!='/state/queue' or cfg.get('authorization')!='/private/auth/authorization.json' or
        cfg.get('context')!='/private/context/context.json' or cfg.get('public_key')!='/private/inbox/manager-public.pem' or
        cfg.get('public_key_sha256')!=hashlib.sha256(public).hexdigest() or host.worker_private_bytes(plan.inbox/'manager-public.pem',10000,8192)!=public):raise Stop('A2_ENROLLMENT_BINDING')


WORKER=r'''
import importlib.util,json,sys
from pathlib import Path
sys.path[:0]=['/workspace/runner/src','/workspace/runner/autonomous-development']
from github_inbox import GitHub,Inbox,production_executor,load_enrollment
from bridge_queue import BridgeQueue
from queue_store import TaskStore
from signal_desk.task_bridge.adapters import HermesAgent
args=json.loads(sys.argv[1]);action=args['action']
if action=='preflight':
    gate='enrollment-context'
    try:
        cfg,policy,key=load_enrollment('/private/inbox/enrollment.json')
        agent=HermesAgent(cfg['runner'],cfg['queue'],policy,context_path=cfg['context'])
        gate='cli-flags'
        if '--provider' not in agent._installed_help():raise ValueError()
        gate='context-git';agent.preflight()
    except Exception:
        print(json.dumps({'preflight':False,'gate':gate}));raise SystemExit(0)
    print(json.dumps({'preflight':True}));raise SystemExit(0)
class ExactFeed:
    def __init__(self):self.client=None
    def remote(self):
        if self.client is None:self.client=GitHub()
        return self.client
    def latest(self,issue):return args['cursors'][str(issue)]
    def comments(self,issue,since,etag=None):
        if issue==41:yield self.comment(41,args['grant_id']),None
    def comment(self,issue,ident):
        if issue!=41 or ident not in (args['instruction_id'],args['grant_id']):raise ValueError('exact feed')
        return self.remote().comment(issue,ident)
    def publish(self,issue,text):return self.remote().publish(issue,text)
def executor(config,policy):
    queue=BridgeQueue(TaskStore(Path(config['queue']),create=False))
    if queue.store.all_tasks():raise ValueError('queue not empty')
    entry=queue.enqueue(Path(config['runner']),Path(config['authorization']),Path(config['context']),runner_commit=config['runner_commit'])
    spec=importlib.util.spec_from_file_location('reviewed_a2_factory','/opt/factory-a2.py')
    factory=importlib.util.module_from_spec(spec);spec.loader.exec_module(factory)
    result=queue.dispatch_one(factory.production_bridge)
    if result.get('id')!=entry['id']:raise ValueError('queue mapping')
    return result
box=Inbox('/private/inbox/enrollment.json',Path('/state/github-inbox'),ExactFeed() if action in ('enroll','tick') else None,executor)
if action=='enroll':box.enroll(args['start']);result=box.doctor()
elif action=='doctor':result=box.doctor()
elif action=='enable':box.enable();result=box.doctor()
elif action=='disable':box.disable();result=box.doctor()
elif action=='tick':result=box.tick()
else:raise ValueError('action')
print(json.dumps(result,sort_keys=True))
'''


def native_evidence(plan,host,queue_id=None):
    # All worker files are claims. Bind their mapping, project only bounded enum/
    # numeric fields, and never imply an independently proven provider cause.
    evidence={'receipt':'missing-or-uncertain'}
    if not isinstance(queue_id,str) or not re.fullmatch('[0-9a-f]{32}',queue_id):return evidence
    path=plan.state/'queue'/queue_id/'bridge'/'native-cli-exit.json'
    if not os.path.lexists(path):return evidence
    rec=json.loads(host.worker_private_bytes(path,10000,4096))
    entry=json.loads(host.worker_private_bytes(path.parents[1]/'state.json',10000,8192))
    allowed={'unclassified','cli_option_rejected','write_root_refused','http_401_observed','http_403_observed','http_429_observed'}
    run=rec.get('run_id')
    if (rec.get('schema')!=1 or rec.get('queue_id')!=queue_id or not isinstance(run,str) or not re.fullmatch('[0-9a-f]{32}',run) or
        entry.get('id')!=queue_id or entry.get('kind')!='bridge' or entry.get('invocations')!=1 or entry.get('bridge_run_id')!=run or
        entry.get('authorization_identity')!=AUTHORITY or entry.get('bridge_state')!='/state/queue/'+queue_id+'/bridge' or
        rec.get('observed_stderr_pattern') not in allowed):return evidence
    bounded=lambda value,cap:value if type(value) is int and 0<=value<=cap else None
    return {'queue_id':queue_id,'run_id':run,'observed_stderr_pattern':rec['observed_stderr_pattern'],
        'exit_code':bounded(rec.get('exit_code'),255),'signal':bounded(rec.get('signal'),64),
        'duration_ms':bounded(rec.get('duration_ms'),3600000),'stderr_bytes':bounded(rec.get('stderr_bytes'),2**31-1),
        'note':'operator-produced native pattern; not verified cause/quota/entitlement'}


def configure(root,plan,old,host,auth,cleanup,readback,signer,ident,row,scope):
    ops=host.HostOperations(plan,runner=host.CommandRunner(deadline=time.monotonic()+1800),deadline=time.monotonic()+1800)
    original_preflight=ops.preflight
    original_mounts=auth.mounts
    auth.correction_file=lambda p:root/'helpers'/'worker-preflight-v3.py'
    def base_mounts(p,service):
        return {k:(rw or service=='inbox-worker' and k[0] in ('/workspace/runner','/state')) for k,rw in original_mounts(p,service).items()}
    auth.mounts=base_mounts
    extras={('/private/auth/github-token',str(old.auth/'github-token')):False,
            ('/opt/child-capture-a2.py',str(root/'helpers'/'capture.py')):False,
            ('/opt/factory-a2.py',str(root/'helpers'/'factory.py')):False,
            ('/opt/queued-write-root.py',str(root/'helpers'/'write_root.py')):False}
    def preflight():
        original_preflight();auth.preflight(ops,host)
        rendered=json.loads(ops._compose('config','--format','json'))
        rendered=auth.auth_config(rendered,plan)
        worker=rendered['services']['inbox-worker']
        worker['environment']['HERMES_WRITE_SAFE_ROOT']='/state/unclaimed'
        for (target,source),rw in extras.items():worker['volumes'].append(dict(type='bind',source=source,target=target,read_only=True,bind={'create_host_path':False}))
        auth.mounts=lambda p,s:base_mounts(p,s)| (extras if s=='inbox-worker' else {})
        put(root/'runtime.json',rendered)
        auth.configure(ops,root/'runtime.json')
    ops.preflight=preflight
    def call(action,*extra,timeout=60):
        args=dict(action=action,instruction_id=ident,grant_id=getattr(ops,'a2_grant',None),cursors=scope.cursors,start=scope.start)
        if action=='preflight':pass
        elif action not in ('enroll','doctor','enable','disable','tick'):raise Stop('A2_ACTION')
        try:value=json.loads(ops._worker('/opt/hermes/.venv/bin/python','-I','-B','-c',WORKER,json.dumps(args),timeout=timeout))
        except BaseException:
            if action=='tick':
                try:ops._stop_claim_runtime()
                except BaseException:ops.runtime_stopped=False
            raise
        return value
    ops._inbox=call
    def login():
        owner=json.loads(ops._worker('/opt/hermes/.venv/bin/python','-I','-B','/opt/worker-preflight.py',timeout=35))
        if owner!={'worker_owner_git':True,'credential_helper_configured':True}:raise Stop('A2_OWNER_PREFLIGHT')
        result=call('preflight',timeout=150)
        if result!={'preflight':True}:raise Stop('A2_CLI_CONTEXT_PREFLIGHT')
    ops.login=login
    client=signer.GitHub(plan.signer_token,deadline=ops.deadline)
    ops.signer=client;ops.github=client
    def claim():
        binding(plan,scope,host,auth)
        if instruction(client,ident)!=row:raise Stop('A2_INSTRUCTION_CHANGED')
        if ops.deadline-time.monotonic()<1260:raise Stop('A2_TIME_RESERVE')
        grant=signer.sign_once(scope,plan.signer_state_root,client,41,ident,
            lambda payload,*,deadline:signer.openssl_sign(plan.signer_key,payload,deadline=deadline),
            verify=lambda payload,sig,*,deadline:signer.openssl_verify(plan.signer_public,payload,sig,deadline=deadline),deadline=ops.deadline-540)
        ops.a2_grant=grant['grant_id'];ops.claim_status=call('tick',timeout=min(1260,ops.deadline-time.monotonic()-420))
        state=call('doctor');current=state.get('claim')
        if current is None and ops.claim_status.get('status') in ('empty','rate-limited','waiting'):return ()
        if (not isinstance(current,dict) or current.get('grant_id')!=ops.a2_grant or current.get('instruction_id')!=ident or
            current.get('publication_intent') is not None or current.get('status') not in ('blocked','review-ready')):raise Stop('A2_CLAIM_UNCERTAIN')
        ops.a2_claim=current
        # A returned, durably blocked claim is not a reason to leave the known
        # containers running. Preserve the claim; exact root-only cleanup follows.
        return ()
    ops.one_bridge_claim=claim
    def reconcile():
        state=call('doctor');current=state.get('claim')
        if not isinstance(current,dict) or current.get('status')!='review-ready':return 'blocked'
        q=current.get('queue_id')
        if not isinstance(q,str) or not re.fullmatch('[0-9a-f]{32}',q):return 'unknown'
        remote=readback.verify(plan.state/'queue',q,DIGEST,AUTHORITY,client.get)
        if remote.get('verified') is not True:return 'blocked'
        ops.remote_result=remote;return 'review-ready'
    ops.reconcile=reconcile
    def clean(resources):
        cleanup.cleanup(ops,auth,lambda name,data:put(root/'journals'/(name+'.json'),data))
        return resources
    ops.cleanup=clean
    def cleanup_readback(resources):
        actual=ops._docker('ps','-aq','--no-trunc').splitlines(),ops._docker('network','ls','-q','--no-trunc').splitlines()
        return (ops.baseline is not None and all(set(a)==set(b.splitlines()) for a,b in zip(actual,ops.baseline)) and
            'SD_ONCE_IN' not in ops._call(['iptables','-S']) and 'SD_ONCE_FWD' not in ops._call(['iptables','-S']))
    ops.cleanup_readback=cleanup_readback
    original_report=ops.report
    def report(summary):
        ops.remote_result=dict(ops.remote_result or {},native_evidence=native_evidence(plan,host,(getattr(ops,'a2_claim',None) or {}).get('queue_id')))
        return original_report(summary)
    ops.report=report
    return ops


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workspace');p.add_argument('--release-commit');p.add_argument('--release-sha256');p.add_argument('--instruction-id',type=int)
    p.add_argument('--execute-new-approved-attempt',action='store_true');a=p.parse_args()
    if not a.execute_new_approved_attempt:
        print('A2 REVIEW ONLY: no host, credential, model, grant, task or timer action');return 0
    try:
        if os.geteuid()!=0 or not sys.stdin.isatty() or not a.workspace or not a.release_commit or not a.release_sha256 or not a.instruction_id:raise Stop('APPROVED_OPERATOR_INPUTS_REQUIRED')
        blobs=release(a.release_commit,a.release_sha256)
        auth=module('_reviewed_a2_auth',blobs['auth'])
        cleanup=module('_reviewed_a2_cleanup',blobs['cleanup']);diag=module('_reviewed_a2_diagnostic',blobs['diag'])
        w,raw,_=diag.inspect(a.workspace);auth.root_dir(w)
        bundle=Path(raw['bundle']);auth.root_dir(bundle)
        for name in ('operator_lifecycle.py','operator_host_v2.py'):
            expected=auth.RELEASE['ops/bridge_one_shot/'+name]
            if hashlib.sha256(auth.blob(bundle/name)).hexdigest()!=expected:raise Stop('ROOT_ENGINE_DIGEST')
        auth.protected_module('operator_lifecycle',bundle/'operator_lifecycle.py')
        signer=module('root_signer',blobs['signer']);host=auth.protected_module('_reviewed_a2_host',bundle/'operator_host_v2.py')
        host.check_signer_binding=lambda plan,scope:binding(plan,scope,host,auth)
        readback=module('_reviewed_a2_readback',blobs['readback'])
        old=host.load_plan(w/(OLD+'-runtime-v2-plan.json'));auth.root_dir(old.source)
        root,plan,row,scope_data=stage(w,old,host,auth,signer,blobs,a.instruction_id)
        scope=signer.Scope(**scope_data)
        ops=configure(root,plan,old,host,auth,cleanup,readback,signer,a.instruction_id,row,scope)
        journal=host.Journal(plan.journal_parent/ATTEMPT,ATTEMPT)
        before=signal.getsignal(signal.SIGTERM)
        def interrupted(*_):raise KeyboardInterrupt()
        signal.signal(signal.SIGTERM,interrupted)
        try:result=host.run_once(journal,ops,deadline=ops.deadline)
        finally:signal.signal(signal.SIGTERM,before)
        print('A2_RESULT: '+result['status'])
        print('OWN_RUNTIME_CLEANUP: '+('EXACT_IDS_VERIFIED' if result['cleanup_verified'] else 'UNVERIFIED_PRESERVE'))
        print('GITHUB_REPORT: '+str(result['report_receipt'] or 'UNVERIFIED_PRESERVE'))
        print('OLD_RUN_AUTH_HISTORY: PRESERVED; HOURLY_TIMER: NOT_INSTALLED')
        return 0 if result['status']=='review-ready' and result['cleanup_verified'] else 2
    except (Exception,KeyboardInterrupt) as exc:
        code=str(exc) if isinstance(exc,Stop) and re.fullmatch('[A-Z0-9_]{1,80}',str(exc)) else 'UNVERIFIED_PRESERVE'
        print('STOP: A2 '+code+'; preserve all state; no retry or guessed cleanup');return 1

if __name__=='__main__':raise SystemExit(main())
