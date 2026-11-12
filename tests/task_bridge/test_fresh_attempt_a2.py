"""Offline regression gates; never contact GitHub, Docker or a provider."""
import ast
import copy
from dataclasses import dataclass,fields
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace,ModuleType
import pytest

ROOT=Path(__file__).resolve().parents[2]
def load(name,path):
    sp=importlib.util.spec_from_file_location(name,ROOT/path)
    m=importlib.util.module_from_spec(sp);sys.modules[name]=m;sp.loader.exec_module(m);return m
m=load('a2_entry','ops/bridge_one_shot/attempt_a2.py')
capture=load('a2_capture','ops/github_inbox/child_capture_a2.py')
factory=load('a2_factory','ops/github_inbox/factory_a2.py')
write_root=load('a2_write_root','ops/github_inbox/queued_write_root.py')


def test_default_entry_and_capture_do_nothing(monkeypatch,capsys):
    for module in (m,capture):
        monkeypatch.setattr(sys,'argv',['entry'])
        monkeypatch.setattr(module.os,'geteuid',lambda:pytest.fail('no identity or host read in review'))
        assert module.main()==0
    assert 'REVIEW ONLY' in capsys.readouterr().out


def test_manifest_digest_scope_and_each_dependency_before_import():
    contents={path:('trusted '+path).encode() for path in m.FILES.values()}
    manifest={path:hashlib.sha256(b).hexdigest() for path,b in contents.items()}
    raw=m.canonical(manifest);sha=hashlib.sha256(raw).hexdigest()
    get=lambda commit,path:raw if path.endswith('release_a2.json') else contents[path]
    assert set(m.release('a'*40,sha,get))==set(m.FILES)
    with pytest.raises(m.Stop,match='MANIFEST_DIGEST'):m.release('a'*40,'0'*64,get)
    contents[next(iter(contents))]=b'changed'
    with pytest.raises(m.Stop,match='FILE_DIGEST'):m.release('a'*40,sha,get)
    raw=m.canonical(dict(manifest,unknown='a'*64))
    with pytest.raises(m.Stop,match='MANIFEST_SCOPE'):m.release('a'*40,hashlib.sha256(raw).hexdigest(),get)


def row():return dict(id=7000000000,issue_url='https://api.github.com/repos/'+m.REPO+'/issues/41',
    body='RUN FROZEN DEVELOPMENT TASK #43 AUTH '+m.AUTHORITY,created_at='2026-11-12T14:00:00Z',updated_at='2026-11-12T14:00:00Z',
    user={'id':35579049},performed_via_github_app={'id':1144995})

@pytest.mark.parametrize('field,value',[
 ('id',7000000001),('issue_url','other'),('body','arbitrary commit evidence'),('updated_at','2026-11-12T14:00:01Z'),
 ('created_at','invalid'),('user',{'id':1}),('performed_via_github_app',None)])
def test_exact_new_instruction_scope_refuses_changes(field,value):
    v=row();client=SimpleNamespace(comment=lambda *a:v)
    assert m.instruction(client,v['id'])==v
    v[field]=value
    with pytest.raises(m.Stop):m.instruction(client,7000000000)
    with pytest.raises(m.Stop):m.instruction(client,6775497757)


def test_factory_reuses_queued_mapping_and_restores_environment(monkeypatch):
    q='a'*32;r='b'*32
    entry=dict(id=q,bridge_run_id=r,bridge_state='/state/queue/'+q+'/bridge',kind='bridge')
    seen=[]
    def native(prompt,tree):return ['hermes','chat','--query-file',str(prompt),'--oneshot','--quiet','--in',str(tree),'--max-turns','12','--run-budget','600']
    agent=SimpleNamespace(command=native)
    bridge=SimpleNamespace(agent=agent)
    def once():
        seen.append(os.environ['HERMES_WRITE_SAFE_ROOT'])
        argv=agent.command(Path(entry['bridge_state'])/'prompt',Path(seen[-1]))
        assert argv==['/opt/hermes/.venv/bin/python','-I','-B','/opt/child-capture-a2.py','--capture-approved-child','--queue-id',q,'--run-id',r]
        raise RuntimeError('synthetic crash')
    bridge.once=once
    mod=ModuleType('bridge_queue');mod.BridgeQueue=SimpleNamespace(production_bridge=lambda e,p:bridge)
    monkeypatch.setitem(sys.modules,'bridge_queue',mod)
    original=importlib.util.spec_from_file_location
    monkeypatch.setattr(factory.importlib.util,'spec_from_file_location',lambda n,p:original(n,ROOT/'ops/github_inbox/queued_write_root.py'))
    monkeypatch.setenv('HERMES_WRITE_SAFE_ROOT','sentinel')
    actual=factory.production_bridge(entry,None)
    with pytest.raises(ValueError,match='command mapping'):actual.agent.command('wrong','wrong')
    with pytest.raises(RuntimeError):actual.once()
    assert seen==['/state/queue/'+q+'/bridge/worktrees/'+r]
    assert os.environ['HERMES_WRITE_SAFE_ROOT']=='sentinel'
    for key,value in [('id','not-id'),('bridge_run_id','old/run'),('bridge_state','/state/worktrees'),('kind','legacy')]:
        bad=dict(entry);bad[key]=value
        with pytest.raises(ValueError):factory.production_bridge(bad,None)


def test_real_native_capture_is_bounded_sanitized_and_refuses_replay(monkeypatch):
    # Real local child, synthetic output only. No Hermes or provider.
    with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
        state=Path(directory);state.chmod(0o700)
        argv=[sys.executable,'-c',"import os,sys;sys.stderr.write('PRIVATE_SECRET'*10000+' HTTP 429');sys.exit(7)"]
        uid=os.geteuid();assert capture.capture(argv,state,'a'*32,'b'*32,uid=uid)==7
        receipt=json.loads((state/'native-cli-exit.json').read_text())
        assert receipt['exit_code']==7 and receipt['signal'] is None
        assert receipt['stderr_bytes']==len('PRIVATE_SECRET'*10000+' HTTP 429')
        assert receipt['observed_stderr_pattern']=='http_429_observed'
        assert 'PRIVATE_SECRET' not in ''.join(p.read_text() for p in state.iterdir())
        with pytest.raises(FileExistsError):capture.capture(argv,state,'a'*32,'b'*32,uid=uid,launcher=lambda *a,**k:pytest.fail('replay'))
        (state/'native-cli-exit.json').unlink()  # fixture only: intent alone must still refuse
        with pytest.raises(FileExistsError):capture.capture(argv,state,'a'*32,'b'*32,uid=uid,launcher=lambda *a,**k:pytest.fail('replay'))


def test_spawn_failure_preserves_intent_without_retry():
    with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
        state=Path(directory);state.chmod(0o700)
        def fail(*a,**kw):raise OSError('synthetic')
        with pytest.raises(OSError):capture.capture(['never'],state,'a'*32,'b'*32,uid=os.geteuid(),launcher=fail)
        assert (state/'native-cli-intent.json').is_file() and not (state/'native-cli-exit.json').exists()
        with pytest.raises(FileExistsError):capture.capture(['never'],state,'a'*32,'b'*32,uid=os.geteuid(),launcher=fail)


def test_child_keeps_outer_process_group_and_closes_after_exit():
    seen=[]
    with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
        state=Path(directory);state.chmod(0o700)
        def launch(argv,**kw):
            assert 'start_new_session' not in kw and 'process_group' not in kw
            child=subprocess.Popen(argv,**kw);seen.append(os.getpgid(child.pid));return child
        assert capture.capture([sys.executable,'-c','pass'],state,'a'*32,'b'*32,uid=os.geteuid(),launcher=launch)==0
        assert seen==[os.getpgrp()]

@pytest.mark.parametrize('data,expected',[(b'No such option: --query-file','cli_option_rejected'),
 (b'outside HERMES_WRITE_SAFE_ROOT','write_root_refused'),(b'HTTP 401','http_401_observed'),
 (b'HTTP 403','http_403_observed'),(b'quota? elapsed time','unclassified')])
def test_failure_pattern_is_observation_only(data,expected):assert capture.pattern(data)==expected


def test_root_clone_checks_git_before_ownership_transfer(monkeypatch,tmp_path):
    dst=tmp_path/'new';seen=[]
    def run(args):
        seen.append(('git',list(map(str,args))))
        if args[0]=='clone':dst.mkdir();(dst/'.git').mkdir();(dst/'tracked').write_text('fixture')
        if 'rev-parse' in args:return m.PIN.encode()+b'\n'
        return b''
    monkeypatch.setattr(m.os,'chown',lambda p,u,g:seen.append(('chown',str(p))))
    m.clone(tmp_path/'source',dst,run=run)
    first=next(i for i,e in enumerate(seen) if e[0]=='chown')
    assert all(e[0]=='git' for e in seen[:first]) and all(e[0]=='chown' for e in seen[first:])
    assert not any('safe.directory' in str(e) for e in seen)


def worker_seam(monkeypatch,action):
    seen=[];gh=ModuleType('github_inbox');adapters=ModuleType('signal_desk.task_bridge.adapters')
    class Remote:
        def __init__(self):seen.append('credential')
        def comment(self,i,n):seen.append(('GET',i,n));return {'id':n}
    class Agent:
        def __init__(self,*a,**kw):pass
        def _installed_help(self):seen.append('help');return '--provider'
        def preflight(self):seen.append('context-git')
    class Inbox:
        def __init__(self,e,s,gh,executor):self.gh=gh
        def enroll(self,start):seen.append(('cursor',self.gh.latest(41),self.gh.latest(45)))
        def doctor(self):return {'enabled':False}
        def tick(self):
            seen.append(('feed',list(self.gh.comments(41,'start'))+list(self.gh.comments(45,'start'))))
            with pytest.raises(ValueError):self.gh.comment(41,6775497757)
            return {'status':'empty'}
    gh.GitHub=Remote;gh.Inbox=Inbox;gh.production_executor=lambda *a:pytest.fail('no executor')
    gh.load_enrollment=lambda *a:({'runner':'r','queue':'q','context':'c'},None,None)
    adapters.HermesAgent=Agent
    monkeypatch.setitem(sys.modules,'github_inbox',gh);monkeypatch.setitem(sys.modules,'signal_desk.task_bridge.adapters',adapters)
    bq=ModuleType('bridge_queue');bq.BridgeQueue=object;qs=ModuleType('queue_store');qs.TaskStore=object
    monkeypatch.setitem(sys.modules,'bridge_queue',bq);monkeypatch.setitem(sys.modules,'queue_store',qs)
    args=dict(action=action,cursors={'41':6999999999,'45':6713729283},start='2026-11-12T14:00:00Z',instruction_id=7000000000,grant_id=7000000001)
    monkeypatch.setattr(sys,'argv',['worker',json.dumps(args)])
    try:exec(compile(m.WORKER,'<a2-worker>','exec'),{})
    except SystemExit as exc:assert exc.code==0
    return seen


def test_empty_poll_and_preflight_never_request_model(monkeypatch):
    assert worker_seam(monkeypatch,'preflight')==['help','context-git']
    assert worker_seam(monkeypatch,'enroll')==[('cursor',6999999999,6713729283)]
    assert worker_seam(monkeypatch,'tick')==['credential',('GET',41,7000000001),('feed',[({'id':7000000001},None)])]


def test_frozen_supervision_limits_are_not_replaced():
    # The wrapper owns capture only. The reviewed outer agent owns kill/reap/time.
    source=(ROOT/'src/signal_desk/task_bridge/adapters.py').read_text()
    assert 'def execute(self, argv, timeout=630)' in source and 'start_new_session=True' in source
    assert 'start_new_session=True' not in (ROOT/'ops/github_inbox/child_capture_a2.py').read_text()
    assert '--max-turns\',\'12\',\'--run-budget\',\'600' in (ROOT/'ops/github_inbox/child_capture_a2.py').read_text()
    assert m.BRANCH!='issue43-one-shot-review-note' and m.AUTHORITY!='2cc0a42be444e93491b14f37bd9fdbd0c71e65d30305d7b79c24b32c94c59cfa'


def test_real_git_clone_and_partial_destination_refusal(tmp_path):
    source=tmp_path/'source';source.mkdir()
    def git(*a):return subprocess.run(['git',*map(str,a)],check=True,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL).stdout
    git('init',source);git('-C',source,'config','user.name','fixture');git('-C',source,'config','user.email','fixture@example.invalid')
    (source/'file').write_text('fixture');git('-C',source,'add','file');git('-C',source,'commit','-m','fixture')
    pin=git('-C',source,'rev-parse','HEAD').decode().strip();dst=tmp_path/'new'
    m.clone(source,dst,pin=pin,uid=os.geteuid(),gid=os.getegid())
    assert git('-C',dst,'rev-parse','HEAD').strip()==pin.encode() and not git('-C',dst,'status','--porcelain')
    before=(dst/'file').read_bytes()
    with pytest.raises(subprocess.CalledProcessError):m.clone(source,dst,pin=pin,uid=os.geteuid(),gid=os.getegid())
    assert (dst/'file').read_bytes()==before


def configured(monkeypatch,tmp_path,claim=None):
    captured=[];calls=[]
    class Ops:
        def __init__(self,plan,**kw):
            self.plan=plan;self.deadline=m.time.monotonic()+1800;self.remote_result=None
            self.preflight=lambda:None;self.report=lambda s:'123'
        def _worker(self,*a,**kw):
            args=json.loads(a[-1]);calls.append(args['action'])
            if args['action']=='tick':return json.dumps({'status':'blocked'})
            if args['action']=='doctor':return json.dumps({'claim':claim})
            return '{}'
        def _compose(self,*a,**kw):return json.dumps(rendered)
        def _stop_claim_runtime(self):calls.append('exact-stop')
    plan=SimpleNamespace(**{k:tmp_path/k for k in ('bundle','runner','state','auth','context','home','venv','inbox','signer_token','signer_key','signer_public','signer_state_root','journal_parent')})
    old=SimpleNamespace(auth=tmp_path/'old-auth')
    a=load('a2_auth_fixture','ops/bridge_one_shot/authenticate_worker_clone_fix.py')
    rendered={'services':{}}
    for service in ('inbox-worker','connect-proxy'):
        rendered['services'][service]={'environment':{},'volumes':[dict(type='bind',target=t,source=s) for t,s in a.mounts(plan,service)]}
    for v in rendered['services']['inbox-worker']['volumes']:
        if v['target']=='/opt/worker-preflight.py':v['source']=str(plan.bundle/'worker_preflight.py')
    monkeypatch.setattr(a,'preflight',lambda *args:None)
    monkeypatch.setattr(a,'configure',lambda ops,path:captured.append(json.loads(path.read_text())))
    client=SimpleNamespace()
    signed=[]
    def sign(*args,**kw):signed.append(args);return {'grant_id':7000000001}
    signer=SimpleNamespace(GitHub=lambda *a,**kw:client,sign_once=sign,openssl_sign=lambda *a:None,openssl_verify=lambda *a:None)
    host=SimpleNamespace(HostOperations=Ops,CommandRunner=lambda **kw:None)
    scope=SimpleNamespace(cursors={'41':6999999999,'45':6713729283},start=row()['created_at'])
    monkeypatch.setattr(m,'binding',lambda *a:None)
    monkeypatch.setattr(m,'instruction',lambda *a:row())
    monkeypatch.setattr(m,'put',lambda p,b,**kw:p.write_bytes(m.canonical(b) if not isinstance(b,bytes) else b))
    ops=m.configure(tmp_path,plan,old,host,a,None,None,signer,7000000000,row(),scope)
    return ops,a,plan,old,captured,calls,signed


def test_real_compose_transform_has_exact_rw_ro_boundaries(monkeypatch,tmp_path):
    ops,auth,plan,old,captured,_,_=configured(monkeypatch,tmp_path)
    ops.preflight();cfg=captured[0];worker=cfg['services']['inbox-worker']
    wanted=auth.mounts(plan,'inbox-worker')
    actual={(v['target'],v['source']):not v['read_only'] for v in worker['volumes']}
    assert actual==wanted and len(actual)==len(worker['volumes'])
    assert {target for (target,source),rw in actual.items() if rw}=={'/workspace/runner','/state','/worker-home'}
    assert actual[('/private/auth/github-token',str(old.auth/'github-token'))] is False
    assert actual[('/opt/queued-write-root.py',str(tmp_path/'helpers/write_root.py'))] is False
    assert all(not rw for (target,source),rw in actual.items() if target.startswith('/opt/'))
    assert worker['environment']['HERMES_WRITE_SAFE_ROOT']=='/state/unclaimed'


def test_known_blocked_claim_is_returned_once_for_exact_cleanup(monkeypatch,tmp_path):
    current=dict(status='blocked',grant_id=7000000001,instruction_id=7000000000,publication_intent=None)
    ops,_,_,_,_,calls,signed=configured(monkeypatch,tmp_path,current)
    assert ops.one_bridge_claim()==()
    assert calls==['tick','doctor'] and len(signed)==1

@pytest.mark.parametrize('change',[{'publication_intent':'blocked'},{'grant_id':1},{'instruction_id':6775497757},{'status':'running'}])
def test_ambiguous_claim_does_not_become_cleanup_authority(monkeypatch,tmp_path,change):
    current=dict(status='blocked',grant_id=7000000001,instruction_id=7000000000,publication_intent=None);current.update(change)
    ops,_,_,_,_,calls,signed=configured(monkeypatch,tmp_path,current)
    with pytest.raises(m.Stop,match='CLAIM_UNCERTAIN'):ops.one_bridge_claim()
    assert calls==['tick','doctor'] and len(signed)==1


def test_native_evidence_binds_queue_run_authority_and_never_copies_raw(tmp_path):
    q='a'*32;r='b'*32;state=tmp_path/'state';folder=state/'queue'/q/'bridge';folder.mkdir(parents=True)
    rec=dict(schema=1,queue_id=q,run_id=r,exit_code=1,signal=None,duration_ms=3,stderr_bytes=99,
             observed_stderr_pattern='unclassified',raw='PRIVATE')
    entry=dict(kind='bridge',id=q,bridge_run_id=r,invocations=1,authorization_identity=m.AUTHORITY,bridge_state='/state/queue/'+q+'/bridge')
    (folder/'native-cli-exit.json').write_text(json.dumps(rec));(folder.parent/'state.json').write_text(json.dumps(entry))
    host=SimpleNamespace(worker_private_bytes=lambda p,*a:p.read_bytes());plan=SimpleNamespace(state=state)
    result=m.native_evidence(plan,host);assert result['run_id']==r and 'PRIVATE' not in json.dumps(result)
    entry['authorization_identity']='old';(folder.parent/'state.json').write_text(json.dumps(entry))
    assert m.native_evidence(plan,host)=={'receipt':'missing-or-uncertain'}


def test_fresh_stage_requires_original_transition_cleanup_and_unused_remote(monkeypatch,tmp_path):
    # Real one-use directory/files, injected ownership only: this runner is not a
    # root/cross-UID fixture. No credentials read; no GitHub/host effects.
    host_module=load('a2_plan_fixture','ops/bridge_one_shot/operator_host_v2.py')
    Plan=host_module.Plan
    raw={f.name:str(tmp_path/f.name) for f in fields(Plan)}
    raw.update(attempt=m.OLD,merge='c'*40,image='sha256:'+'d'*64,uid=10000,gid=10000,overall_seconds=1800,
               signer_state_root='/var/lib/signal-desk/issue41-signer-claims')
    for k in ('bundle','auth','home'):raw[k]=str(tmp_path/(m.OLD+'-runtime-v2-'+k))
    original=dict(raw)
    for k in ('bundle','auth','home'):original[k]=str(tmp_path/k)
    (tmp_path/(m.OLD+'-bootstrap-spec.json')).write_text(json.dumps(original))
    (tmp_path/(m.OLD+'-runtime-v2-plan.json')).write_text(json.dumps(raw))
    plan=Plan(**{k:Path(v) if k not in ('attempt','merge','image','uid','gid','overall_seconds') else v for k,v in raw.items()})
    cleanup=tmp_path/(m.OLD+'-exact-cleanup-01');cleanup.mkdir()
    (cleanup/'report-receipt.json').write_text(json.dumps({'id':6822780163,'verified':True}))
    (cleanup/'runtime-cleanup-verified.json').write_text(json.dumps(dict(containers_removed=2,networks_removed=2,scoped_firewall_removed=True)))
    (plan.signer_public).write_bytes(b'public-key')
    task={'state':'open','body':(ROOT/'tests/task_bridge/fixtures/issue43_body.txt').read_text()}
    exists=[True];gets=[]
    class Client:
        def comment(self,*a):return row()
        def task(self,*a):return task
        def get(self,path):
            gets.append(path)
            return {'missing':True} if '/git/ref/' in path and not exists[0] else ([] if '/pulls?' in path else {'object':{}})
    signer=SimpleNamespace(GitHub=lambda *a,**kw:Client())
    auth=SimpleNamespace(root_dir=lambda *a:None,blob=lambda p,**kw:p.read_bytes(),RELEASE={},SOURCE=raw['merge'],WORKER_PREFLIGHT_V3=b'reviewed')
    monkeypatch.setattr(m,'put',lambda p,data,*a,**kw:p.write_bytes(data if isinstance(data,bytes) else m.canonical(data)))
    monkeypatch.setattr(m,'mkdir',lambda p,*a:p.mkdir(mode=0o700))
    cloned=[]
    with pytest.raises(m.Stop,match='NEW_BRANCH_OR_PR'):m.stage(tmp_path,plan,host_module,auth,signer,{'capture':b'reviewed'},7000000000,clone_runner=lambda *a:cloned.append(a))
    assert not (tmp_path/m.ATTEMPT).exists() and not cloned
    exists[0]=False
    root,new,row_value,scope=m.stage(tmp_path,plan,host_module,auth,signer,{'capture':b'reviewed'},7000000000,clone_runner=lambda source,dest:cloned.append((source,dest)))
    assert new.state!=plan.state and new.runner!=plan.runner and new.auth!=plan.auth and new.inbox!=plan.inbox
    assert (new.home,new.context,new.venv,new.signer_state_root)==(plan.home,plan.context,plan.venv,plan.signer_state_root)
    assert (root/'auth/github-token').read_bytes()==b''
    assert scope['cursors']['41']==6999999999 and scope['authority_identity']==m.AUTHORITY
    assert json.loads((root/'auth/authorization.json').read_text())==m.POLICY
    with pytest.raises(m.Stop,match='FRESH_ATTEMPT_EXISTS'):m.stage(tmp_path,plan,host_module,auth,signer,{},7000000000)
    assert len(cloned)==1


def test_a2_readback_requires_new_branch_and_exact_remote_artifact(tmp_path,monkeypatch):
    # Reuse the existing complete SQLite + independent GitHub fixture, changing
    # only the separately versioned branch. This is an offline simulated API.
    fixture=load('a2_remote_fixture','tests/task_bridge/test_bridge_readback.py')
    monkeypatch.setattr(fixture,'BRANCH',m.BRANCH)
    monkeypatch.setattr(fixture,'BODY','Refs #43\n\nReviewed task branch: `'+m.BRANCH+'`.\n')
    verifier=load('a2_remote_verifier','ops/bridge_one_shot/bridge_readback_a2.py')
    queue,db,api=fixture.fixture(tmp_path)
    result=verifier.verify(queue,fixture.QUEUE,fixture.DIGEST,'e'*64,api.__getitem__)
    assert result['verified'] is True and result['observed_ci']=='pending'
    branch='/repos/'+m.REPO+'/git/ref/heads/'+m.BRANCH
    api[branch]['ref']='refs/heads/issue43-one-shot-review-note'
    assert verifier.verify(queue,fixture.QUEUE,fixture.DIGEST,'e'*64,api.__getitem__)=={'verified':False}

@pytest.mark.parametrize('status', [401,403,429,500])
def test_only_explicit_new_branch_404_can_be_absence(monkeypatch,status):
    signer=load('a2_root_http','ops/github_inbox/root_signer_a2.py')
    client=signer.GitHub.__new__(signer.GitHub);client._token='synthetic';client.deadline=None
    code=[404]
    class Opener:
        def open(self,req,**kw):raise signer.urllib.error.HTTPError(req.full_url,code[0],'synthetic',{},None)
    monkeypatch.setattr(signer.urllib.request,'build_opener',lambda *a:Opener())
    path='/repos/'+m.REPO+'/git/ref/heads/'+m.BRANCH
    assert client.get(path)=={'missing':True}
    code[0]=status
    with pytest.raises((RuntimeError,signer.RateLimited)):client.get(path)
    code[0]=404
    with pytest.raises(RuntimeError):client.task(43)
    for method,path in [('POST','/repos/'+m.REPO+'/git/ref/heads/'+m.BRANCH),('DELETE','/repos/'+m.REPO+'/issues/41/comments'),
        ('GET','/repos/'+m.REPO+'/actions/secrets'),('GET','/repos/'+m.REPO+'/git/ref/heads/issue43-one-shot-review-note')]:
        with pytest.raises(ValueError):client._request(method,path)
