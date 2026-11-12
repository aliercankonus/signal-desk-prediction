"""One-use read-only consumed a2 diagnostic; optional existing-credential report.
No Git, Docker, provider auth, signing, model, task, cleanup or timer operation.
Default is inert. --inspect requires root TTY; --report adds one issue receipt.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import sys
import time
import types
import urllib.request

REPO='aliercankonus/signal-desk-prediction'
REPORT=6827131876
RUN='2a07298e691f47558826903aef0b2a3d'
QUEUE='7859a7198b8948ce953c1759feb106ce'
ATTEMPT='issue43-a2-20261112'
ENTRY='issue43-a2-diagnostic-01'
SOURCE='7c5703cd61f9add02e6159df2a86b5476a54c8ae'
SOURCES={'diag':('ops/bridge_one_shot/consumed_a2_evidence.py','4df0dd634229cf5f6feef3d04438ada062e8ed8044639a380f35e09499667f7c'),
 'signer':('ops/github_inbox/root_signer_a2.py','b882031012336e7285d63673f07bcfa23691b24e70ef0fa129a51bdb281b34be')}


def public(name):
    path,digest=SOURCES[name]
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*a,**kw):raise ValueError('redirect')
    if signal.getitimer(signal.ITIMER_REAL)[0]:raise ValueError('timer')
    old=signal.getsignal(signal.SIGALRM)
    def timeout(*a):raise TimeoutError()
    signal.signal(signal.SIGALRM,timeout);signal.alarm(20)
    try:
        with urllib.request.build_opener(NoRedirect).open('https://raw.githubusercontent.com/'+REPO+'/'+SOURCE+'/'+path,timeout=15) as r:data=r.read(65537)
    finally:signal.alarm(0);signal.signal(signal.SIGALRM,old)
    if not data or len(data)>65536 or hashlib.sha256(data).hexdigest()!=digest:raise ValueError('dependency digest')
    result=types.ModuleType('_verified_diagnostic_'+name);sys.modules[result.__name__]=result
    exec(compile(data,'<verified-public-diagnostic>','exec'),result.__dict__);return result


def inspect(w,diag,*,worker_uid=10000):
    w=Path(w)
    if not w.is_absolute() or '..' in w.parts:raise ValueError('workspace')
    diag.directory(w,os.geteuid())
    integration=w/'issue43-a2-integration-01'
    plan=json.loads(diag.read_bytes(integration/'plan.json',os.geteuid()))
    if (plan.get('attempt')!=ATTEMPT or plan.get('state')!=str(w/ATTEMPT/'state') or plan.get('journal_parent')!=str(integration/'journals') or
        plan.get('runner')!=str(w/ATTEMPT/'object-clone-recovery-02'/'runner') or plan.get('uid')!=worker_uid or plan.get('gid')!=10000):raise ValueError('exact integration plan')
    phase_path=integration/'journals'/'approved-runtime-01'/'phase.json'
    phase=json.loads(diag.read_bytes(phase_path,os.geteuid()))
    if (phase.get('attempt')!=ATTEMPT or phase.get('status')!='blocked' or phase.get('cleanup_verified') is not True or phase.get('owned')!=[] or
        phase.get('intent') is not None or phase.get('unresolved_effect') is not None or phase.get('report_receipt')!=str(REPORT)):raise ValueError('cleanup report identity')
    root=w/ATTEMPT/'state'/'queue'/QUEUE
    data=diag.inspect_queue(root,uid=worker_uid)
    native=json.loads(diag.read_bytes(root/'bridge'/'native-cli-exit.json',worker_uid,4096))
    if (native.get('queue_id')!=QUEUE or native.get('run_id')!=RUN or native.get('schema')!=1 or native.get('exit_code')!=1 or
        native.get('signal') is not None or native.get('stderr_bytes')!=0 or native.get('observed_stderr_pattern')!='unclassified'):raise ValueError('native receipt identity')
    data['native']={'exit_code':1,'signal':None,'duration_ms':diag.number(native.get('duration_ms')),'stderr_bytes':0,'pattern':'unclassified'}
    checkpoint=root/'bridge'/'recovery-checkpoint.json'
    if os.path.lexists(checkpoint):
        row=json.loads(diag.read_bytes(checkpoint,worker_uid,4096))
        if row.get('identity',{}).get('run_id')!=RUN:raise ValueError('checkpoint identity')
        data['checkpoint']={'stage':diag.enum(row.get('stage'),diag.CHECKPOINTS),'last_confirmed':diag.enum(row.get('last_confirmed'),diag.CHECKPOINTS),'head':diag.head(row.get('head'))}
    data.update(cleanup_report=REPORT,cleanup_verified=True,task=False,model=False,timer=False)
    if len(json.dumps(data).encode())>4096:raise ValueError('projection bound')
    return data


def write(path,data):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as f:json.dump(data,f,sort_keys=True);f.flush();os.fsync(f.fileno())
    fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)


def publish(w,data,client):
    row=client.comment(41,REPORT)
    if row.get('id')!=REPORT or row.get('issue_url')!='https://api.github.com/repos/'+REPO+'/issues/41' or row.get('user',{}).get('id')!=35579049 or row.get('created_at')!=row.get('updated_at'):raise ValueError('authenticated old report')
    old=json.loads(row['body']);evidence=(old.get('remote_result') or {}).get('native_evidence') or {}
    if old.get('operator_attempt')!=ATTEMPT or old.get('cleanup_verified') is not True or old.get('result')!='blocked' or (evidence.get('queue_id'),evidence.get('run_id'),evidence.get('exit_code'),evidence.get('stderr_bytes'))!=(QUEUE,RUN,1,0):raise ValueError('old report scope')
    text=json.dumps(data,sort_keys=True,separators=(',',':'))
    folder=Path(w)/ENTRY;folder.mkdir(mode=0o700)  # No resume after POST ambiguity.
    fd=os.open(folder.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)
    write(folder/'intent.json',{'body_sha256':hashlib.sha256(text.encode()).hexdigest(),'retry':False})
    ident=client.publish(41,text)
    if type(ident) is not int or ident<=REPORT:raise ValueError('new report ID')
    check=client.comment(41,ident)
    if check.get('id')!=ident or check.get('issue_url')!=row['issue_url'] or check.get('body')!=text:raise ValueError('report readback')
    write(folder/'receipt.json',{'id':ident,'verified':True});return ident


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--workspace');p.add_argument('--inspect',action='store_true');p.add_argument('--report',action='store_true');a=p.parse_args()
    if not a.inspect:print('REVIEW ONLY: no host or credential action');return 0
    phase='inputs'
    try:
        if os.geteuid()!=0 or not sys.stdin.isatty():raise ValueError('root terminal')
        w=Path(a.workspace)
        if os.path.lexists(w/ENTRY):raise FileExistsError('preserve prior diagnostic')
        phase='read-only-inspection';diag=public('diag');data=inspect(w,diag)
        if a.report:
            phase='report-only';signer=public('signer')
            client=signer.GitHub(w/'root-github-token',deadline=time.monotonic()+90)
            print('GITHUB_A2_DIAGNOSTIC_REPORT: '+str(publish(w,data,client)))
        print('A2_DIAGNOSTIC: COMPLETE; CONSUMED_STATE: PRESERVED; NO_MODEL_TASK_RUNTIME_ACTION');return 0
    except (Exception,KeyboardInterrupt) as exc:
        print('STOP: A2_DIAGNOSTIC PHASE='+phase+' TYPE='+type(exc).__name__+'; preserve state; no retry or cleanup');return 1

if __name__=='__main__':raise SystemExit(main())
