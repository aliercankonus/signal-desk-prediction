import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace,ModuleType
import pytest

ROOT=Path(__file__).resolve().parents[2]
sp=importlib.util.spec_from_file_location('authorized43',ROOT/'ops/bridge_one_shot/run_authorized_issue43.py')
m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m)


def instruction():return dict(id=m.INSTRUCTION_ID,body=m.BODY,created_at=m.INSTRUCTION_TIME,
    updated_at=m.INSTRUCTION_TIME,issue_url='https://api.github.com/repos/aliercankonus/signal-desk-prediction/issues/41',
    user={'id':35579049},performed_via_github_app={'id':1144995})


def test_exact_comment_identity_is_required_even_for_same_actor_and_app():
    row=instruction();assert m.exact_instruction(row)==row
    for key,value in [('id',m.INSTRUCTION_ID+1),('body',m.BODY+' '),('created_at','2026-11-10T18:17:43Z'),
        ('updated_at','2026-11-10T18:17:43Z'),('user',{'id':1}),('performed_via_github_app',{'id':1}),
        ('issue_url',row['issue_url'].replace('/41','/45'))]:
        bad=copy.deepcopy(row);bad[key]=value
        with pytest.raises(m.Stop):m.exact_instruction(bad)


def success_receipt():return dict(schema=1,github_readonly_verified=True,device_cli_success=True,
    cleanup_verified=True,partial_startup=False,failure=None,failure_phase=None,worker_preflight_code=None,
    child_exit_code=None,enrollment=False,signing=False,dispatch=False,timer=False,
    model_entitlement='UNPROVEN',manager_exclusivity='UNPROVEN')


def phase():return dict(version=1,attempt=m.ATTEMPT,phase='cleanup',status='pending',intent=None,
    unresolved_effect=None,owned=[],cleanup_verified=True,report_receipt=None)


def test_success_auth_history_is_accepted_without_auth_store_read_and_prior_is_preserved(tmp_path):
    # Metadata seam only; actual-root helper/journal is separately tested below.
    a=SimpleNamespace(CORRECTED_JOURNAL=m.ATTEMPT+'-auth-only-02',WORKER_PREFLIGHT_V3=b'reviewed',
        root_dir=lambda p:None,blob=lambda p,**kw:p.read_bytes(),failure_records=lambda r,p:None)
    p=SimpleNamespace(journal_parent=tmp_path)
    first=tmp_path/(m.ATTEMPT+'-auth-only-01');second=tmp_path/a.CORRECTED_JOURNAL
    first.mkdir();second.mkdir()
    for path in (first,second):
        (path/'phase.json').write_text(json.dumps(phase()))
        (path/'auth-only-receipt.json').write_text(json.dumps(success_receipt()))
        (path/'compose.auth-only.json').write_text('{}')
    (second/'worker_preflight_v3.py').write_bytes(b'reviewed')
    before={str(f):f.read_bytes() for p in (first,second) for f in p.iterdir()}
    m.history(p,a)
    assert all(Path(f).read_bytes()==v for f,v in before.items())
    for key,value in [('github_readonly_verified',False),('device_cli_success',False),
        ('cleanup_verified',False),('partial_startup',True),('dispatch',True),('failure','unknown')]:
        bad=success_receipt();bad[key]=value
        (second/'auth-only-receipt.json').write_text(json.dumps(bad))
        with pytest.raises(m.Stop):m.history(p,a)
    (second/'auth-only-receipt.json').write_text(json.dumps(success_receipt()))
    bad=phase();bad['unresolved_effect']='cleanup';(second/'phase.json').write_text(json.dumps(bad))
    with pytest.raises(m.Stop):m.history(p,a)
    (second/'phase.json').write_text(json.dumps(phase()))
    (tmp_path/m.TASK_JOURNAL).mkdir()
    with pytest.raises(m.Stop,match='HISTORY_PRESERVE'):m.history(p,a)


def worker_seam(monkeypatch,action,*,preflight_error=False):
    seen=[];namespace={}
    gh=ModuleType('github_inbox');adapters=ModuleType('signal_desk.task_bridge.adapters')
    class Remote:
        def __init__(self):seen.append('credential')
        def comment(self,issue,ident):seen.append(('GET',issue,ident));return {'id':ident}
        def publish(self,*a):seen.append(('POST',*a));return 1
    class Agent:
        def __init__(self,*a,**kw):pass
        def check(self):seen.append('agent-check')
        def preflight(self):
            seen.append('agent-preflight')
            if preflight_error:raise ValueError('incompatible CLI or execution context')
    class Inbox:
        def __init__(self,enrollment,state,github,executor):self.gh=github
        def enroll(self,start):
            seen.append(('snapshot',self.gh.latest(41),self.gh.latest(45),start))
        def doctor(self):return {'enabled':False}
        def tick(self):
            rows=list(self.gh.comments(41,'old'))+list(self.gh.comments(45,'old'))
            seen.append(('feed',rows))
            with pytest.raises(ValueError):self.gh.comment(41,999)
            with pytest.raises(ValueError):self.gh.comment(45,m.INSTRUCTION_ID)
            return {'status':'empty'}
    gh.GitHub=Remote;gh.Inbox=Inbox;gh.production_executor=lambda *a:pytest.fail('no model')
    gh.load_enrollment=lambda *a:({'runner':'runner','queue':'queue','context':'context'},None,None)
    adapters.HermesAgent=Agent
    monkeypatch.setitem(sys.modules,'github_inbox',gh)
    monkeypatch.setitem(sys.modules,'signal_desk.task_bridge.adapters',adapters)
    args=dict(action=action,cursors=m.CURSORS,start='2026-11-10T00:00:00Z',
        grant_id=m.INSTRUCTION_ID+10,instruction_id=m.INSTRUCTION_ID)
    monkeypatch.setenv('HERMES_WRITE_SAFE_ROOT','/state/worktrees')
    monkeypatch.setattr(sys,'argv',['worker',json.dumps(args)])
    try:exec(compile(m.WORKER,'<reviewed-worker>','exec'),namespace)
    except SystemExit as exc:assert exc.code==0
    return seen


def test_explicit_frozen_cursor_snapshot_cannot_skip_the_approved_instruction(monkeypatch):
    seen=worker_seam(monkeypatch,'enroll')
    assert seen==[('snapshot',m.CURSORS['41'],m.CURSORS['45'],'2026-11-10T00:00:00Z')]
    assert m.CURSORS['41']<m.INSTRUCTION_ID


def test_worker_feed_contains_only_root_verified_grant_no_arbitrary_comments(monkeypatch):
    seen=worker_seam(monkeypatch,'tick')
    assert seen==['credential',('GET',41,m.INSTRUCTION_ID+10),
        ('feed',[({'id':m.INSTRUCTION_ID+10},None)])]


def test_cli_context_preflight_makes_no_credential_or_executor_request(monkeypatch):
    assert worker_seam(monkeypatch,'preflight')==['agent-check','agent-preflight']
    assert worker_seam(monkeypatch,'preflight',preflight_error=True)==['agent-check','agent-preflight']


def test_only_task_checkout_and_state_gain_write_access():
    old={('/workspace/runner','/runner'):False,('/state','/state'):False,
        ('/private/auth','/auth'):False,('/worker-home','/home'):True}
    a=SimpleNamespace(_original_mounts=lambda p,s:old)
    actual=m.task_mounts(a,None,'inbox-worker')
    assert actual=={k:(k[0] in ('/workspace/runner','/state','/worker-home')) for k in old}
    assert m.task_mounts(a,None,'connect-proxy')==old


def test_real_main_uses_fresh_task_journal_and_never_auth_entry(monkeypatch,capsys,tmp_path):
    lifecycle_spec=importlib.util.spec_from_file_location('task_lifecycle',ROOT/'ops/bridge_one_shot/operator_lifecycle.py')
    lifecycle=importlib.util.module_from_spec(lifecycle_spec);sys.modules['task_lifecycle']=lifecycle;lifecycle_spec.loader.exec_module(lifecycle)
    # Real Journal enforces its own ancestor ownership; home private temp below.
    with tempfile.TemporaryDirectory(dir=Path.home()) as folder:
        parent=Path(folder);parent.chmod(0o700)
        for name in (m.ATTEMPT+'-auth-only-01',m.ATTEMPT+'-auth-only-02'):
            p=parent/name;p.mkdir(mode=0o700);(p/'preserved').write_bytes(b'history')
        plan=SimpleNamespace(journal_parent=parent,attempt=m.ATTEMPT,overall_seconds=3600)
        chosen=[]
        def run(journal,ops,**kw):
            journal.create();chosen.append(journal.directory)
            assert journal.directory.name==m.TASK_JOURNAL
            return dict(status='review-ready',cleanup_verified=True,report_receipt='123')
        host=SimpleNamespace(Journal=lifecycle.Journal,run_once=run,CommandRunner=lambda **kw:None,HostOperations=lambda *a,**kw:object())
        auth=SimpleNamespace(mounts=lambda *a:{})
        monkeypatch.setattr(m,'auth_module',lambda p:auth);monkeypatch.setattr(m,'load',lambda *a:(host,plan))
        monkeypatch.setattr(m,'prepare',lambda *a:None);monkeypatch.setattr(sys.stdin,'isatty',lambda:True)
        monkeypatch.setattr(sys,'argv',['entry','--workspace','/private','--auth-helper','/reviewed','--execute-approved-issue43'])
        assert m.main()==0;assert chosen==[parent/m.TASK_JOURNAL]
        assert m.main()==1
        assert 'PRESERVE_STATE' in capsys.readouterr().out
        for name in (m.ATTEMPT+'-auth-only-01',m.ATTEMPT+'-auth-only-02'):
            assert (parent/name/'preserved').read_bytes()==b'history'


def test_root_helper_digest_guard_loads_only_known_code():
    if os.geteuid()!=0:pytest.skip('actual root metadata admission in CI')
    source=ROOT/'ops/bridge_one_shot/authenticate_worker_clone_fix.py'
    with tempfile.TemporaryDirectory(dir=Path.home()) as folder:
        d=Path(folder);d.chmod(0o700);p=d/'auth.py';p.write_bytes(source.read_bytes());p.chmod(0o600)
        assert m.auth_module(p).CORRECTED_JOURNAL.endswith('-auth-only-02')
        p.write_bytes(source.read_bytes()+b'\n')
        with pytest.raises(m.Stop,match='HELPER_DIGEST'):m.auth_module(p)
        p.unlink();p.symlink_to(source)
        with pytest.raises(m.Stop):m.auth_module(p)


@pytest.mark.parametrize('gate',[None,'TASK_CLI_FLAGS','TASK_CONTEXT_OR_GIT'])
def test_full_lifecycle_wiring_preflights_before_single_sign_and_tick(monkeypatch,gate):
    lifecycle_spec=importlib.util.spec_from_file_location('task_lifecycle_flow',ROOT/'ops/bridge_one_shot/operator_lifecycle.py')
    lifecycle=importlib.util.module_from_spec(lifecycle_spec);sys.modules['task_lifecycle_flow']=lifecycle;lifecycle_spec.loader.exec_module(lifecycle)
    events=[]
    signer=ModuleType('root_signer');scope=SimpleNamespace(authority_identity=m.AUTHORITY,cursors=m.CURSORS,start='2026-11-10T00:00:00Z')
    signer.load_scope=lambda p:scope
    class Client:
        def __init__(self,*a,**kw):pass
        def comment(self,issue,ident):return instruction()
    signer.GitHub=Client
    def sign(scope,store,client,issue,ident,sign,**kw):
        assert issue==41 and ident==m.INSTRUCTION_ID
        assert client.comment(41,ident)==instruction()
        events.append('sign');return {'status':'verified','grant_id':m.INSTRUCTION_ID+20}
    signer.sign_once=sign
    signer.openssl_sign=lambda *a,**kw:pytest.fail('fake signature only')
    signer.openssl_verify=lambda *a,**kw:pytest.fail('fake signature only')
    monkeypatch.setitem(sys.modules,'root_signer',signer)
    with tempfile.TemporaryDirectory(dir=Path.home()) as folder:
        parent=Path(folder);parent.chmod(0o700)
        state=parent/'state';state.mkdir(mode=0o700)
        p=SimpleNamespace(journal_parent=parent,attempt=m.ATTEMPT,signer_policy=parent/'policy',
            signer_token=parent/'token',signer_state_root=parent/'signer',state=state)
        class Ops:
            plan=p;deadline=100000000000;enrollment_inode=None;claim_status=None
            failure_stage=None
            def preflight(self):events.append('original-preflight')
            def _compose(self,*a):return '{"services":{"inbox-worker":{"environment":{}}}}'
            def start_isolation(self):events.append('start');return (lifecycle.Owned('worker','exact-id',m.ATTEMPT),)
            def _worker(self,*args,**kw):
                if args[-1]=='/opt/worker-preflight.py':return json.dumps(dict(worker_owner_git=True,credential_helper_configured=True))
                action=json.loads(args[-1]);events.append(action['action'])
                if action['action']=='preflight':return json.dumps({'task_preflight':True} if gate is None else {'task_preflight':False,'gate':gate})
                if action['action']=='tick':
                    assert action['grant_id']==m.INSTRUCTION_ID+20
                    return '{"status":"review-ready"}'
                return '{}'
            def _inbox(self,*a,**kw):pytest.fail('frozen latest snapshot must be replaced')
            def login(self):pytest.fail('no device login')
            def github_reads(self):events.append('github-read')
            def enroll_disabled(self):
                self._inbox('enroll','--start',scope.start)
                d=state/'github-inbox';d.mkdir();self.enrollment_inode=str(d.stat().st_ino)
                return (lifecycle.Owned('enrollment',self.enrollment_inode,m.ATTEMPT),)
            def enable_inbox(self):self._inbox('enable');return ()
            def one_bridge_claim(self):pytest.fail('only pinned sign')
            def reconcile(self):return 'review-ready' if self.claim_status else 'blocked'
            def inspect_owned(self,r):return True
            def cleanup(self,r):events.append('cleanup');return r
            def cleanup_readback(self,r):return True
            def report(self,summary):events.append('report');return '123'
            def report_readback(self,*a):return True
        ops=Ops()
        auth=SimpleNamespace(preflight=lambda *a:events.append('metadata'),auth_config=lambda r,p:r,
            configure=lambda *a:events.append('configured'))
        journal=lifecycle.Journal(parent/m.TASK_JOURNAL,m.ATTEMPT)
        m.prepare(journal,ops,None,auth)
        result=lifecycle.run_once(journal,ops,deadline=100000000000)
        assert result['cleanup_verified'] and result['report_receipt']=='123'
        assert events.index('preflight')<events.index('github-read') if gate is None else 'github-read' not in events
        if gate is None:
            assert events.count('sign')==events.count('tick')==1
            assert events.index('preflight')<events.index('enroll')<events.index('sign')<events.index('tick')<events.index('cleanup')
            assert result['status']=='review-ready'
        else:
            assert 'sign' not in events and 'tick' not in events and 'enroll' not in events
            assert result['status']=='blocked' and ops.failure_stage=='LOGIN' and ops.failure_code==gate


@pytest.mark.parametrize('outcome',['review-ready','quota-fixture','crash-fixture'])
def test_exact_feed_with_actual_inbox_persists_claim_before_one_executor_and_never_retries(monkeypatch,outcome):
    import ast,base64,hashlib
    sys.path.insert(0,str(ROOT/'autonomous-development'))
    from github_inbox import Inbox,REPO
    tree=ast.parse(m.WORKER)
    feed_node=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='ExactFeed')
    grant_id=m.INSTRUCTION_ID+30
    args=dict(cursors=m.CURSORS,instruction_id=m.INSTRUCTION_ID,grant_id=grant_id)
    payload=dict(v=1,repo=REPO,issue=41,instruction_id=m.INSTRUCTION_ID,
        instruction_sha256=hashlib.sha256(m.BODY.encode()).hexdigest(),task_issue=43,
        authority_identity=m.AUTHORITY,runner_commit='e84021a786004456a12de9e25eae50d191da6cf1',scope='development-only')
    grant=dict(id=grant_id,body=json.dumps({'signal_desk_grant_v1':{'payload':payload,'signature':base64.b64encode(b'x'*64).decode()}}),
        created_at=m.INSTRUCTION_TIME,updated_at=m.INSTRUCTION_TIME)
    gets=[];posts=[];calls=[]
    class Remote:
        def comment(self,issue,ident):
            gets.append((issue,ident));return instruction() if ident==m.INSTRUCTION_ID else grant
        def publish(self,issue,text):posts.append(json.loads(text));return len(posts)
    scope={'args':args,'GitHub':Remote};exec(compile(ast.Module(body=[feed_node],type_ignores=[]),'<reviewed-feed>','exec'),scope)
    feed=scope['ExactFeed']()
    with tempfile.TemporaryDirectory(dir=Path.home()) as folder:
        d=Path(folder);d.chmod(0o700);enrollment=d/'enrollment';enrollment.write_bytes(b'publicfixture');enrollment.chmod(0o600)
        queue=d/'queue';queue.mkdir(mode=0o700)
        cfg=dict(runner_commit=payload['runner_commit'],interval_seconds=300,queue=str(queue))
        def execute(*_):
            assert box._read()['claim']['status']=='claimed'
            calls.append('executor')
            if outcome!='review-ready':raise RuntimeError(outcome)
            return dict(status='review-ready',id='a'*32,ci='pending')
        box=Inbox(enrollment,d/'inbox',feed,execute,verifier=lambda *a:True)
        box._config=lambda:(cfg,SimpleNamespace(issue=43,identity=m.AUTHORITY),b'fixture')
        box.enroll('2026-11-10T00:00:00Z')
        assert box.doctor()['cursor']==m.CURSORS and not box.doctor()['enabled']
        assert not gets and not posts and not calls
        box.enable();result=box.tick()
        assert result['status']==('review-ready' if outcome=='review-ready' else 'blocked')
        assert calls==['executor'] and gets[0]==(41,grant_id)
        assert box.tick()['status']=='blocked' and calls==['executor']
        box.disable();assert not box.doctor()['enabled']
        assert box.doctor()['claim']['instruction_id']==m.INSTRUCTION_ID


def test_operator_block_is_parseable_and_binds_both_immutable_reviewed_files():
    import ast,hashlib,re,subprocess
    text=(ROOT/'ops/bridge_one_shot/RUN_AUTHORIZED_ISSUE43.md').read_text()
    block=re.findall(r'```bash\n(.*?)```',text,re.S)[0]
    assert not any(re.match(r'^\s*\d+\s*[:|]',line) for line in block.splitlines())
    subprocess.run(['bash','-n'],input=block.encode(),check=True)
    code=block.split("<<'PY'\n",1)[1].split('\nPY\n',1)[0]
    tree=ast.parse(code)
    entries=ast.literal_eval(next(n.value for n in tree.body if isinstance(n,ast.Assign) and
        any(isinstance(t,ast.Name) and t.id=='entries' for t in n.targets)))
    assert entries[0][0]=='09aa854e8e1751f62286c0c1fc686a634d299729'
    assert entries[1][0]=='5d1a005ae3a3a5816fd94ae085d6d81797e4cdf6'
    for _,path,digest in entries:assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==digest
    assert '--execute-approved-issue43' in code and '--authenticate' not in code
