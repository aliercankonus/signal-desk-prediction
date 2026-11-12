import importlib.util,json,os,sys,tempfile
from pathlib import Path
from types import SimpleNamespace
import pytest
ROOT=Path(__file__).resolve().parents[2]
def load(name,p):
 s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
m=load('reporter',ROOT/'ops/bridge_one_shot/report_consumed_a2.py')
f=load('fixture',ROOT/'tests/task_bridge/test_capture_v3_and_a2_evidence.py');d=f.d

def fixture(w):
 integ=w/'issue43-a2-integration-01';journal=integ/'journals/approved-runtime-01';journal.mkdir(parents=True,mode=0o700)
 for p in (integ,integ/'journals'):p.chmod(0o700)
 def put(p,v):p.write_text(json.dumps(v));p.chmod(0o600)
 put(integ/'plan.json',dict(attempt=m.ATTEMPT,state=str(w/m.ATTEMPT/'state'),runner=str(w/m.ATTEMPT/'object-clone-recovery-02/runner'),journal_parent=str(integ/'journals'),uid=os.geteuid(),gid=10000))
 put(journal/'phase.json',dict(attempt=m.ATTEMPT,status='blocked',cleanup_verified=True,owned=[],intent=None,unresolved_effect=None,report_receipt=str(m.REPORT)))
 parent=w/m.ATTEMPT/'state/queue';parent.mkdir(parents=True,mode=0o700)
 for p in (w/m.ATTEMPT,w/m.ATTEMPT/'state'):p.chmod(0o700)
 root=parent/m.QUEUE;f.dbfixture(root)
 put(root/'bridge/native-cli-exit.json',dict(schema=1,queue_id=m.QUEUE,run_id=m.RUN,exit_code=1,signal=None,stderr_bytes=0,duration_ms=22556,observed_stderr_pattern='unclassified'))
 return integ,root


def test_real_readonly_inspection_and_byte_preservation():
 with tempfile.TemporaryDirectory(dir=Path.home()) as n:
  w=Path(n);w.chmod(0o700);integ,root=fixture(w)
  before={p:p.read_bytes() for p in w.rglob('*') if p.is_file()}
  result=m.inspect(w,d,worker_uid=os.geteuid())
  assert result['bridge']['failure']['exit_code']==1 and result['native']['stderr_bytes']==0 and result['model'] is False
  assert all(p.read_bytes()==b for p,b in before.items())

@pytest.mark.parametrize('change',['cleanup','report','native','queue'])
def test_scope_changes_refuse_without_writes(change):
 with tempfile.TemporaryDirectory(dir=Path.home()) as n:
  w=Path(n);w.chmod(0o700);integ,root=fixture(w)
  if change in ('cleanup','report'):
   p=integ/'journals/approved-runtime-01/phase.json';v=json.loads(p.read_text());v['cleanup_verified' if change=='cleanup' else 'report_receipt']=False if change=='cleanup' else '1'
  elif change=='native':p=root/'bridge/native-cli-exit.json';v=json.loads(p.read_text());v['run_id']='a'*32
  else:p=root/'state.json';v=json.loads(p.read_text());v['invocations']=2
  p.write_text(json.dumps(v))
  with pytest.raises((ValueError,d.Stop)):m.inspect(w,d,worker_uid=os.geteuid())
  assert not (w/m.ENTRY).exists()


def client(fail=False):
 posts=[]
 old=dict(operator_attempt=m.ATTEMPT,cleanup_verified=True,result='blocked',remote_result={'native_evidence':dict(queue_id=m.QUEUE,run_id=m.RUN,exit_code=1,stderr_bytes=0)})
 def comment(issue,ident):return dict(id=ident,issue_url='https://api.github.com/repos/'+m.REPO+'/issues/41',user={'id':35579049},created_at='fixed',updated_at='fixed',body=json.dumps(old) if ident==m.REPORT else posts[0])
 def publish(issue,text):
  posts.append(text)
  if fail:raise TimeoutError('synthetic lost reply')
  return m.REPORT+100
 return SimpleNamespace(comment=comment,publish=publish),posts

@pytest.mark.parametrize('fail',[False,True])
def test_report_one_post_no_replay_and_no_raw_private_data(fail):
 with tempfile.TemporaryDirectory(dir=Path.home()) as n:
  w=Path(n);w.chmod(0o700);_,root=fixture(w)
  import sqlite3
  with sqlite3.connect(root/'bridge/journal.sqlite3') as conn:conn.execute('UPDATE failures SET category=?',('PRIVATE_SENTINEL '+str(w),))
  data=m.inspect(w,d,worker_uid=os.geteuid());c,posts=client(fail)
  if fail:
   with pytest.raises(TimeoutError):m.publish(w,data,c)
  else:assert m.publish(w,data,c)==m.REPORT+100
  with pytest.raises(FileExistsError):m.publish(w,data,c)
  assert len(posts)==1 and str(w) not in posts[0] and 'PRIVATE_SENTINEL' not in posts[0]


def test_default_no_host_or_network(monkeypatch,capsys):
 monkeypatch.setattr(sys,'argv',['entry']);monkeypatch.setattr(m,'public',lambda *a:pytest.fail('inert'))
 assert m.main()==0 and 'REVIEW ONLY' in capsys.readouterr().out


def test_durable_operator_loader_syntax_and_hash():
 import ast,hashlib,subprocess
 text=(ROOT/'ops/bridge_one_shot/REPORT_CONSUMED_A2.md').read_text()
 block=text.split('```bash\n',1)[1].split('\n```',1)[0];subprocess.run(['bash','-n'],input=block.encode(),check=True)
 embedded=block.split("python3 -I -B -c '\n",1)[1].split("\n' \"$DIAG_WORKSPACE\"",1)[0]
 values={n.targets[0].id:n.value.value for n in ast.parse(embedded).body if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and isinstance(n.value,ast.Constant)}
 assert values['expected']==hashlib.sha256((ROOT/'ops/bridge_one_shot/report_consumed_a2.py').read_bytes()).hexdigest()
 assert values['commit']=='9f8114b17d4019a86589db954220cf7fa48c5672'
