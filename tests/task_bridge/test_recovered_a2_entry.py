import importlib.util,json,os,sys,tempfile,time
from pathlib import Path
from dataclasses import dataclass
from types import SimpleNamespace
import pytest
ROOT=Path(__file__).resolve().parents[2]
def load(name,p):
 s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);sys.modules[name]=m;s.loader.exec_module(m);return m
m=load('recovered_entry',ROOT/'ops/bridge_one_shot/run_recovered_a2.py')

def test_default_is_inert(monkeypatch,capsys):
 monkeypatch.setattr(sys,'argv',['entry']);monkeypatch.setattr(m,'public',lambda *a:pytest.fail('no network'))
 assert m.main()==0 and 'REVIEW ONLY' in capsys.readouterr().out

@pytest.mark.parametrize('failure',[None,'one_bridge_claim','start_isolation'])
def test_real_one_way_journal_no_replay_and_ambiguous_effect_preserved(monkeypatch,failure):
 lifecycle=load('recovered_fixture_lifecycle',ROOT/'ops/bridge_one_shot/operator_lifecycle.py')
 @dataclass
 class Plan:
  attempt:str
  journal_parent:Path
  runner:Path
  uid:int
  gid:int
 with tempfile.TemporaryDirectory(dir=Path.home()) as d:
  w=Path(d);w.chmod(0o700);calls=[]
  # Root ownership is a fixture seam only. Exclusive files and the frozen real
  # lifecycle/Journal run unchanged, with no actual host/provider backend.
  def put(p,data,**kw):
   if not isinstance(data,bytes):data=json.dumps(data).encode()
   fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
   with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
  def mkdir(p):p.mkdir(mode=0o700)
  class Ops:
   deadline=time.monotonic()+60
   def preflight(self):calls.append('preflight')
   def start_isolation(self):
    calls.append('start_isolation')
    if failure=='start_isolation':raise TimeoutError('synthetic')
    return (lifecycle.Owned('worker','fixture','fixture-attempt'),)
   def login(self):calls.append('worker-preflight')
   def github_reads(self):calls.append('read-only')
   def enroll_disabled(self):return ()
   def enable_inbox(self):return ()
   def one_bridge_claim(self):
    calls.append('one_bridge_claim')
    if failure=='one_bridge_claim':raise TimeoutError('synthetic')
    return ()
   def reconcile(self):return 'review-ready' if failure is None else 'blocked'
   def inspect_owned(self,r):return True
   def cleanup(self,r):calls.append('cleanup');return r
   def cleanup_readback(self,r):return True
   def report(self,s):calls.append('report');return '123'
   def report_readback(self,*a):return True
  a2=SimpleNamespace(ATTEMPT='fixture-attempt',mkdir=mkdir,put=put,configure=lambda *a:(calls.append('configure') or Ops()))
  blobs={'capture':(ROOT/'ops/github_inbox/child_capture_a2.py').read_bytes(),'factory':(ROOT/'ops/github_inbox/factory_a2.py').read_bytes(),'write_root':(ROOT/'ops/github_inbox/queued_write_root.py').read_bytes()}
  auth=SimpleNamespace(blob=lambda p,**kw:blobs[p.stem],WORKER_PREFLIGHT_V3=b'public fixture')
  runner=w/'new-runner';runner.mkdir(mode=0o755)
  plan=Plan('fixture-attempt',w/'unused',runner,os.geteuid(),os.getegid())
  result=m.integrate(w,plan,plan,a2=a2,auth=auth,host=lifecycle,cleanup=None,readback=None,signer=None,scope=None,row=None)
  assert result['cleanup_verified'] is (failure is None)
  assert ('cleanup' in calls) is (failure is None)
  if failure:assert result['unresolved_effect']==failure
  with pytest.raises(FileExistsError):m.integrate(w,plan,plan,a2=a2,auth=auth,host=lifecycle,cleanup=None,readback=None,signer=None,scope=None,row=None)
  assert calls.count('configure')==1 and calls.count('one_bridge_claim')<=1
  saved=json.loads((w/m.DIRECTORY/'journals/approved-runtime-01/phase.json').read_text())
  assert saved['attempt']=='fixture-attempt'


def test_public_digest_refuses_before_module_execution(monkeypatch):
 class Response:
  def __enter__(self):return self
  def __exit__(self,*a):pass
  def read(self,n):return b'raise AssertionError("not executed")'
 monkeypatch.setattr(m.urllib.request,'build_opener',lambda *a:SimpleNamespace(open=lambda *a,**k:Response()))
 with pytest.raises(ValueError,match='digest'):m.public('a'*40,'ops/public.py','0'*64)


def test_existing_integration_refuses_before_source_or_credential_read(monkeypatch):
 with tempfile.TemporaryDirectory(dir=Path.home()) as d:
  w=Path(d);(w/m.DIRECTORY).mkdir()
  monkeypatch.setattr(sys,'argv',['entry','--workspace',str(w),'--execute-approved-once'])
  monkeypatch.setattr(m.os,'geteuid',lambda:0);monkeypatch.setattr(sys.stdin,'isatty',lambda:True)
  monkeypatch.setattr(m,'public',lambda *a:pytest.fail('no replay network'))
  assert m.main()==1


@pytest.mark.parametrize('branch_exists',[False,True])
def test_top_level_bootstrap_binds_before_any_lifecycle(monkeypatch,branch_exists):
 with tempfile.TemporaryDirectory(dir=Path.home()) as d:
  w=Path(d);events=[];rootbytes=b'root fixture'
  import hashlib
  old=SimpleNamespace(signer_token=w/'token');plan=SimpleNamespace(signer_policy=w/'scope')
  client=SimpleNamespace(get=lambda path:({'missing':True} if not branch_exists else {'object':{}}) if '/git/ref/' in path else [])
  auth=SimpleNamespace(root_dir=lambda p:events.append('private-root'),blob=lambda p:rootbytes,
    RELEASE={'ops/bridge_one_shot/'+n:hashlib.sha256(rootbytes).hexdigest() for n in ('operator_lifecycle.py','operator_host_v2.py')},
    protected_module=lambda name,p:host if name=='_recovered_host' else None)
  host=SimpleNamespace(load_plan=lambda p:old,trusted_worker_mount=lambda *a:None)
  signer=SimpleNamespace(GitHub=lambda p:client,load_scope=lambda p:SimpleNamespace())
  gate=SimpleNamespace(bind=lambda *a,**k:(events.append('gate') or plan))
  a2=SimpleNamespace(OLD='old',ATTEMPT='fixture-attempt',reused_inputs=lambda *a:events.append('reused-inputs'),release=lambda *a:{k:k.encode() for k in ('auth','signer','cleanup','readback')},instruction=lambda *a:{'id':m.INSTRUCTION})
  objects={'_recovered_a2':a2,'_recovered_auth':auth,'_recovered_object_v2':object(),'_recovered_gate':gate,'root_signer':signer,'_recovered_cleanup':object(),'_recovered_readback':object()}
  monkeypatch.setattr(m,'public',lambda *a:b'fixture verified-source seam')
  monkeypatch.setattr(m,'module',lambda name,data:objects[name])
  monkeypatch.setattr(m,'integrate',lambda *a,**k:(events.append('lifecycle') or dict(status='review-ready',cleanup_verified=True,report_receipt='123')))
  monkeypatch.setattr(m.os,'geteuid',lambda:0);monkeypatch.setattr(sys.stdin,'isatty',lambda:True)
  monkeypatch.setattr(sys,'argv',['entry','--workspace',str(w),'--execute-approved-once'])
  assert m.main()==(1 if branch_exists else 0)
  assert 'gate' in events and ('lifecycle' in events) is not branch_exists




def test_only_new_top_directory_tightened_with_no_recursive_changes():
 with tempfile.TemporaryDirectory() as d:
  root=Path(d);runner=root/'runner';runner.mkdir(mode=0o755);old=root/'old';old.mkdir(mode=0o755)
  tracked=runner/'tracked';tracked.write_text('fixture');tracked.chmod(0o644)
  m.tighten_runner(SimpleNamespace(runner=runner,uid=os.geteuid(),gid=os.getegid()))
  assert runner.stat().st_mode&0o777==0o700 and tracked.stat().st_mode&0o777==0o644 and old.stat().st_mode&0o777==0o755
  runner.chmod(0o777)
  with pytest.raises(ValueError):m.tighten_runner(SimpleNamespace(runner=runner,uid=os.geteuid(),gid=os.getegid()))



def test_immutable_operator_loader_syntax_and_digest_binding():
 import ast,hashlib,subprocess
 text=(ROOT/'ops/bridge_one_shot/RUN_RECOVERED_A2.md').read_text()
 block=text.split('```bash\n',1)[1].split('\n```',1)[0]
 subprocess.run(['bash','-n'],input=block.encode(),check=True)
 embedded=block.split("python3 -I -B -c '\n",1)[1].split("\n' \"$RECOVERED_WORKSPACE\"",1)[0]
 values={n.targets[0].id:n.value.value for n in ast.parse(embedded).body if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and isinstance(n.value,ast.Constant)}
 assert values['expected']==hashlib.sha256((ROOT/'ops/bridge_one_shot/run_recovered_a2.py').read_bytes()).hexdigest()
 assert values['commit']=='87f99921d862b272a2e8c36121df97862959f6ba'
