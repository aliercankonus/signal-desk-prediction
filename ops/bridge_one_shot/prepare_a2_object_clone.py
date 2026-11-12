"""Preparation only: recover a new runner beside the preserved a2 partial clone.

No continuation, signing, provider authentication, remote Git fetch, model, Docker or cleanup.
Optional --report uses the existing root GitHub credential for one issue receipt only.
Default is inert. --prepare requires an interactive root operator. A pre-existing
recovery intent/directory always refuses; this is not a retry/resume entry.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import stat
import subprocess
import sys
import signal
import urllib.request
import tempfile
import time

ATTEMPT='issue43-a2-20261112'
RECOVERY='object-clone-recovery-01'
PIN='e84021a786004456a12de9e25eae50d191da6cf1'
REPO='aliercankonus/signal-desk-prediction'
AUTH='1da74bf1d715dc3c0a78809955a2401744e85f64014bdbb57a1e9626e001c037'
INSTRUCTION=6824067293
POLICY=dict(repo=REPO,issue=43,body_digest='c9e4e393ccc506954f0a18e6eaeea7c82ff598b0b41eac642d7f88da1fca73c6',base=PIN,branch='issue43-one-shot-a2')
OLD='issue41-cold-20261110-01'

class Stop(Exception):pass


def private_dir(path,uid=0):
    for p in (path,*path.parents):
        s=p.lstat()
        if not stat.S_ISDIR(s.st_mode) or s.st_uid not in (0,uid) or s.st_mode&0o022:raise Stop('DIRECTORY_ANCESTRY')
    s=path.lstat()
    if s.st_uid!=uid or stat.S_IMODE(s.st_mode)!=0o700:raise Stop('PRIVATE_DIRECTORY')


def blob(path,uid=0,limit=65536):
    private_dir(path.parent,uid)
    s=path.lstat()
    if not stat.S_ISREG(s.st_mode) or s.st_uid!=uid or s.st_mode&0o077 or s.st_nlink!=1 or not 0<s.st_size<=limit:raise Stop('PRIVATE_FILE')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as f:
        t=os.fstat(f.fileno());data=f.read(limit+1)
    key=lambda v:(v.st_dev,v.st_ino,v.st_size,v.st_mtime_ns,v.st_ctime_ns,v.st_mode,v.st_uid,v.st_nlink)
    if key(s)!=key(t) or key(s)!=key(path.lstat()) or len(data)!=s.st_size:raise Stop('FILE_CHANGED')
    return data


def write(path,value):
    data=json.dumps(value,sort_keys=True,separators=(',',':')).encode()
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
    fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)


def git(args,*,deadline=None):
    env=dict(PATH='/usr/bin:/bin',HOME='/nonexistent',LC_ALL='C',GIT_CONFIG_GLOBAL='/dev/null',GIT_CONFIG_NOSYSTEM='1',
        GIT_TERMINAL_PROMPT='0',GIT_NO_LAZY_FETCH='1',GIT_NO_REPLACE_OBJECTS='1',GIT_CONFIG_COUNT='0')
    seconds=min(45,deadline-time.monotonic()) if deadline else 45
    if seconds<=0:raise TimeoutError()
    with tempfile.TemporaryFile() as output:
        def bound():resource.setrlimit(resource.RLIMIT_FSIZE,(65536,65536))
        result=subprocess.run(['/usr/bin/git','--no-optional-locks','-c','core.hooksPath=/dev/null','-c','core.fsmonitor=false',*map(str,args)],
            stdin=subprocess.DEVNULL,stdout=output,stderr=subprocess.DEVNULL,env=env,timeout=seconds,preexec_fn=bound)
        if result.returncode:raise Stop('GIT_EXIT_'+str(result.returncode))
        output.seek(0);data=output.read(65537)
    if len(data)>65536:raise Stop('GIT_OUTPUT_BOUND')
    return data


def refs(source,run=git):
    # for-each-ref succeeds for an empty store, unlike show-ref exit 1.
    result=run(['--git-dir='+str(source),'for-each-ref','--format=%(refname) %(objectname)'])
    files={}
    for name in ('HEAD','FETCH_HEAD','packed-refs','config'):
        p=source/name
        if os.path.lexists(p):
            s=p.lstat()
            if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1 or s.st_size>65536:raise Stop('SOURCE_METADATA')
            files[name]=hashlib.sha256(p.read_bytes()).hexdigest()
    return dict(refs_sha256=hashlib.sha256(result).hexdigest(),files=files)


def clone_exact(source,destination,*,pin=PIN,uid=10000,gid=10000,run=git):
    if not isinstance(pin,str) or not re.fullmatch('[0-9a-f]{40}',pin):raise Stop('PIN')
    if os.path.lexists(destination):raise Stop('DESTINATION_EXISTS')
    if run(['--git-dir='+str(source),'rev-parse','--is-bare-repository']).strip()!=b'true':raise Stop('SOURCE_NOT_BARE')
    if run(['--git-dir='+str(source),'cat-file','-t',pin]).strip()!=b'commit':raise Stop('SOURCE_COMMIT')
    before=refs(source,run)
    run(['clone','--no-local','--no-checkout','--no-hardlinks',source,destination])
    # A bare store can intentionally have the pinned object but NO refs. Clone
    # transfers reachable objects only; explicitly request that exact local SHA.
    # No refspec destination, tags or FETCH_HEAD is written. No remote network.
    run(['-C',destination,'fetch','--no-write-fetch-head','--no-tags',source,pin])
    run(['-C',destination,'remote','set-url','origin','https://github.com/'+REPO+'.git'])
    run(['-C',destination,'config','user.name','Signal Desk Worker'])
    run(['-C',destination,'config','user.email','35579049+aliercankonus@users.noreply.github.com'])
    run(['-C',destination,'checkout','--detach',pin])
    if run(['-C',destination,'rev-parse','HEAD']).strip()!=pin.encode() or run(['-C',destination,'status','--porcelain=v1','--untracked-files=all']):raise Stop('FINAL_HEAD_OR_TREE')
    if refs(source,run)!=before:raise Stop('SOURCE_REFS_CHANGED')
    if os.path.lexists(destination/'.git'/'FETCH_HEAD'):raise Stop('FETCH_HEAD_CREATED')
    # Every root Git operation precedes ownership transfer. No safe.directory.
    for parent,dirs,files in os.walk(destination,followlinks=False):
        for name in dirs+files:
            path=Path(parent)/name
            if path.is_symlink():raise Stop('RUNNER_SYMLINK')
    for parent,dirs,files in os.walk(destination,followlinks=False):
        for name in dirs+files:os.chown(Path(parent)/name,uid,gid)
        os.chown(parent,uid,gid)
    return before


def snapshot(root,*,exclude=RECOVERY,root_uid=0,worker_uid=10000):
    """Metadata/content digest of NONSECRET prefix; old token is empty only.

    Never traverse old auth home, key/token stores or venv. Limit entries/bytes;
    reject symlinks and special/hard-linked files before opening any content.
    """
    expected={'helpers','journals','state','auth','inbox','stage-intent.json','signer-policy.json','runner'}
    if {p.name for p in root.iterdir()}-{exclude}!=expected:raise Stop('PREFIX_INVENTORY')
    inventories={'auth':{'authorization.json','github-token'},'inbox':{'manager-public.pem','enrollment.json'},'state':{'queue'},'helpers':{'auth.py','write_root.py','cleanup.py','diag.py','signer.py','readback.py','capture.py','factory.py','worker-preflight-v3.py'}}
    for folder,names in inventories.items():
        if {p.name for p in (root/folder).iterdir()}!=names:raise Stop('PREFIX_SUBTREE_INVENTORY')
    rows=[];total=0
    for parent,dirs,files in os.walk(root,followlinks=False):
        if Path(parent)==root:dirs[:]=[d for d in dirs if d!=exclude]
        for name in sorted(dirs+files):
            path=Path(parent)/name;s=path.lstat();rel=str(path.relative_to(root))
            if len(rows)>=5000 or not (stat.S_ISDIR(s.st_mode) or stat.S_ISREG(s.st_mode)) or s.st_mode&0o022:raise Stop('PREFIX_METADATA')
            if s.st_uid not in (root_uid,worker_uid):raise Stop('PREFIX_OWNER')
            content=None
            if stat.S_ISREG(s.st_mode):
                if s.st_nlink!=1 or s.st_size>4*1024*1024:raise Stop('PREFIX_FILE')
                if rel.startswith('auth/') and rel not in ('auth/authorization.json','auth/github-token'):raise Stop('UNEXPECTED_AUTH_FILE')
                if rel=='auth/github-token' and s.st_size!=0:raise Stop('TOKEN_NOT_EMPTY')
                total+=s.st_size
                if total>16*1024*1024:raise Stop('PREFIX_BYTE_BOUND')
                fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
                with os.fdopen(fd,'rb') as f:
                    data=f.read(4*1024*1024+1);opened=os.fstat(f.fileno())
                if (opened.st_dev,opened.st_ino,opened.st_size,opened.st_mtime_ns)!=(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns) or len(data)!=s.st_size:raise Stop('PREFIX_CHANGED')
                content=hashlib.sha256(data).hexdigest()
            rows.append((rel,s.st_dev,s.st_ino,s.st_mode,s.st_uid,s.st_gid,s.st_size,s.st_mtime_ns,content))
    return hashlib.sha256(json.dumps(sorted(rows),separators=(',',':')).encode()).hexdigest()


def prepare(workspace,*,uid=10000,gid=10000,root_uid=0,clone=clone_exact):
    w=Path(workspace)
    if not w.is_absolute() or '..' in w.parts or str(w)!=workspace:raise Stop('WORKSPACE')
    private_dir(w,root_uid);root=w/ATTEMPT;private_dir(root,root_uid)
    for name in ('plan.json','stage-ready.json','runtime.json'):
        if os.path.lexists(root/name):raise Stop('STAGE_ADVANCED_PRESERVE')
    private_dir(root/'journals',root_uid)
    if any((root/'journals').iterdir()):raise Stop('JOURNAL_PRESENT')
    private_dir(root/'state',uid);private_dir(root/'state'/'queue',uid)
    if any((root/'state'/'queue').iterdir()) or os.path.lexists(root/'state'/'github-inbox'):raise Stop('CLAIM_OR_QUEUE_PRESENT')
    if os.path.lexists(Path('/var/lib/signal-desk/issue41-signer-claims')/str(INSTRUCTION)):raise Stop('SIGNER_CLAIM_PRESENT')
    intent=json.loads(blob(root/'stage-intent.json',root_uid))
    if intent!=dict(instruction_id=INSTRUCTION,policy=POLICY,retry=False):raise Stop('STAGE_INTENT')
    if json.loads(blob(root/'auth'/'authorization.json',uid))!=POLICY:raise Stop('POLICY')
    old=json.loads(blob(w/(OLD+'-runtime-v2-plan.json'),root_uid))
    if old.get('attempt')!=OLD or old.get('uid')!=uid or old.get('gid')!=gid:raise Stop('OLD_PLAN')
    source=Path(old['source'])
    if not source.is_absolute() or '..' in source.parts:raise Stop('SOURCE_PATH')
    private_dir(source,root_uid)
    runner=root/'runner'
    if runner.is_symlink() or runner.lstat().st_uid!=root_uid or set(p.name for p in runner.iterdir())!={'.git'}:raise Stop('PARTIAL_RUNNER_SCOPE')
    if (runner/'.git').is_symlink() or not (runner/'.git').is_dir():raise Stop('PARTIAL_GIT')
    before=snapshot(root,root_uid=root_uid,worker_uid=uid)
    recovery=root/RECOVERY
    recovery.mkdir(mode=0o700)  # Exclusive one-way intent; existing/partial refuses.
    fd=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)
    write(recovery/'intent.json',dict(schema=1,pin=PIN,old_prefix_sha256=before,task=False,runtime=False))
    stage='exact-object-clone'
    try:
        deadline=time.monotonic()+600
        result=clone(source,recovery/'runner',uid=uid,gid=gid,run=lambda args:git(args,deadline=deadline))
        stage='prefix-readback'
        if snapshot(root,root_uid=root_uid,worker_uid=uid)!=before:raise Stop('PREFIX_CHANGED_PRESERVE')
        write(recovery/'ready.json',dict(schema=1,pin=PIN,source_refs_unchanged=True,old_prefix_sha256=before,
            source_state=result,prepared_runner=True,task=False,runtime=False,signing=False,timer=False))
        return recovery
    except (Exception,KeyboardInterrupt) as exc:
        # Preserve partial clone and intent. Never print raw stderr/private paths.
        write(recovery/'blocked.json',dict(schema=1,stage=stage,error_type=type(exc).__name__,retry=False))
        raise


def report(workspace,recovery,request=None):
    # Existing root GitHub credential is used ONLY for the separately requested
    # preparation receipt. Never provider auth, signing, task or timer access.
    ready=json.loads(blob(recovery/'ready.json'))
    if ready.get('prepared_runner') is not True or ready.get('task') is not False or ready.get('runtime') is not False:raise Stop('READY_RECEIPT')
    payload=dict(preparation='a2-object-clone-recovery-v1',pin=PIN,prepared_runner=True,old_prefix_preserved=True,
        source_refs_unchanged=True,task=False,runtime=False,signing=False,timer=False,retry=False)
    text=json.dumps(payload,sort_keys=True,separators=(',',':'))
    write(recovery/'report-intent.json',dict(body_sha256=hashlib.sha256(text.encode()).hexdigest()))
    if request is None:
        token=blob(Path(workspace)/'root-github-token',limit=1024)
        if b'\n' in token or b'\r' in token:raise Stop('REPORT_CREDENTIAL_FORMAT')
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,*a,**kw):raise Stop('REPORT_REDIRECT')
        def request(method,path,data=None):
            prefix='/repos/'+REPO
            if not (method=='POST' and path==prefix+'/issues/41/comments' or method=='GET' and re.fullmatch(re.escape(prefix)+r'/issues/comments/[1-9][0-9]*',path)):raise Stop('REPORT_SCOPE')
            req=urllib.request.Request('https://api.github.com'+path,method=method,data=json.dumps(data).encode() if data else None,
                headers={'Authorization':'Bearer '+token.decode('ascii'),'Accept':'application/vnd.github+json','Content-Type':'application/json','User-Agent':'signal-desk-preparation-report'})
            if signal.getitimer(signal.ITIMER_REAL)[0]:raise Stop('EXISTING_TIMER')
            previous=signal.getsignal(signal.SIGALRM)
            def timeout(*a):raise TimeoutError()
            signal.signal(signal.SIGALRM,timeout);signal.alarm(20)
            try:
                with urllib.request.build_opener(NoRedirect).open(req,timeout=15) as response:raw=response.read(65537)
            finally:signal.alarm(0);signal.signal(signal.SIGALRM,previous)
            if len(raw)>65536:raise Stop('REPORT_RESPONSE_BOUND')
            return json.loads(raw)
    result=request('POST','/repos/'+REPO+'/issues/41/comments',{'body':text})
    ident=result.get('id')
    if type(ident) is not int or ident<=0:raise Stop('REPORT_ID')
    row=request('GET','/repos/'+REPO+'/issues/comments/'+str(ident))
    if row.get('id')!=ident or row.get('body')!=text or row.get('issue_url')!='https://api.github.com/repos/'+REPO+'/issues/41':raise Stop('REPORT_READBACK')
    write(recovery/'report-receipt.json',dict(id=ident,verified=True))
    return ident


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--workspace');p.add_argument('--prepare',action='store_true');p.add_argument('--report',action='store_true');a=p.parse_args()
    if not a.prepare:print('REVIEW ONLY: no host, Git, credential or task action');return 0
    try:
        if os.geteuid()!=0 or not sys.stdin.isatty() or not a.workspace:raise Stop('ROOT_TERMINAL_REQUIRED')
        recovery=prepare(a.workspace)
        if a.report:print('GITHUB_PREPARATION_REPORT: '+str(report(a.workspace,recovery)))
        print('A2_RUNNER_RECOVERY: PREPARED_ONLY; OLD_PREFIX: PRESERVED; TASK_RUNTIME_SIGNING_TIMER: NOT_STARTED');return 0
    except (Exception,KeyboardInterrupt) as exc:
        code=str(exc) if isinstance(exc,Stop) and re.fullmatch('[A-Z0-9_]{1,80}',str(exc)) else type(exc).__name__
        print('STOP: OBJECT_CLONE '+code+'; preserve state; no retry or cleanup');return 1

if __name__=='__main__':raise SystemExit(main())
