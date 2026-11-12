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
  plan=Plan('fixture-attempt',w/'unused')
  result=m.integrate(w,plan,plan,a2=a2,auth=auth,host=lifecycle,cleanup=None,readback=None,signer=None,scope=None,row=None)
  assert result['cleanup_verified'] is (failure is None)
  assert ('cleanup' in calls) is (failure is None)
  if failure:assert result['unresolved_effect']==failure
  with pytest.raises(FileExistsError):m.integrate(w,plan,plan,a2=a2,auth=auth,host=lifecycle,cleanup=None,readback=None,signer=None,scope=None,row=None)
  assert calls.count('configure')==1 and calls.count('one_bridge_claim')<=1
  saved=json.loads((w/m.DIRECTORY/'journals/approved-runtime-01/phase.json').read_text())
  assert saved['attempt']=='fixture-attempt'
