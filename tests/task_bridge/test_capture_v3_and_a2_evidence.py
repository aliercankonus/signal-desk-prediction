import importlib.util,json,os,sqlite3,sys,tempfile
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[2]
def load(name,path):
 s=importlib.util.spec_from_file_location(name,ROOT/path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
c=load('capture3','ops/github_inbox/child_capture_v3.py');d=load('consumed2','ops/bridge_one_shot/consumed_a2_evidence.py')

@pytest.mark.parametrize('channel',['stdout','stderr'])
def test_stdout_only_failure_and_stderr_only_failure_are_classified_without_raw(channel):
 with tempfile.TemporaryDirectory(dir=Path.home()) as name:
  root=Path(name);root.chmod(0o700)
  code="import sys;sys.%s.write('PRIVATE_SECRET No such option: --query-file');sys.exit(1)"%channel
  assert c.capture([sys.executable,'-c',code],root,'a'*32,'b'*32,uid=os.geteuid())==1
  r=json.loads((root/'native-cli-v3-exit.json').read_text())
  assert r['observed_'+channel+'_pattern']=='cli_option_rejected' and r[channel+'_bytes']>0
  assert all('PRIVATE_SECRET' not in p.read_text() for p in root.iterdir())
  with pytest.raises(FileExistsError):c.capture(['never'],root,'a'*32,'b'*32,uid=os.geteuid(),launcher=lambda *a,**k:pytest.fail('no retry'))


def test_dual_stream_flood_is_drained_without_deadlock_or_raw_persistence():
 with tempfile.TemporaryDirectory(dir=Path.home()) as name:
  root=Path(name);root.chmod(0o700)
  code="import os;[(os.write(1,b'x'*4096),os.write(2,b'y'*4096)) for _ in range(128)]"
  assert c.capture([sys.executable,'-c',code],root,'a'*32,'b'*32,uid=os.geteuid())==0
  r=json.loads((root/'native-cli-v3-exit.json').read_text())
  assert r['stdout_bytes']==r['stderr_bytes']==524288 and r['observed_stdout_pattern']=='unclassified'
  assert (root/'native-cli-v3-exit.json').stat().st_size<1024

@pytest.mark.parametrize('name',['native-cli-intent.json','native-cli-exit.json','native-cli-v3-intent.json','native-cli-v3-exit.json'])
def test_any_old_or_new_intent_receipt_refuses_before_child(name):
 with tempfile.TemporaryDirectory(dir=Path.home()) as folder:
  root=Path(folder);root.chmod(0o700);(root/name).touch()
  with pytest.raises(FileExistsError):c.capture(['never'],root,'a'*32,'b'*32,uid=os.geteuid(),launcher=lambda *a,**k:pytest.fail('no child'))


def test_capture_keeps_outer_supervisor_process_group():
 import subprocess
 with tempfile.TemporaryDirectory(dir=Path.home()) as folder:
  root=Path(folder);root.chmod(0o700);seen=[]
  def launch(argv,**kw):
   assert 'start_new_session' not in kw and 'process_group' not in kw
   p=subprocess.Popen(argv,**kw);seen.append(os.getpgid(p.pid));return p
  assert c.capture([sys.executable,'-c','pass'],root,'a'*32,'b'*32,uid=os.geteuid(),launcher=launch)==0
  assert seen==[os.getpgrp()]


def dbfixture(root):
 root.mkdir(mode=0o700);bridge=root/'bridge';bridge.mkdir(mode=0o700)
 entry=dict(id=d.QUEUE,bridge_run_id=d.RUN,authorization_identity=d.AUTH,invocations=1,status='blocked')
 state=root/'state.json';state.write_text(json.dumps(entry));state.chmod(0o600)
 db=bridge/'journal.sqlite3'
 with sqlite3.connect(db) as conn:
  conn.executescript('CREATE TABLE runs(run_id,status,auth_identity,base,branch,worktree,head,pr_url);CREATE TABLE failures(stage,category,exit_code,signal_number,duration_ms,stop_reason);CREATE TABLE stage_events(id,stage,duration_ms,exit_code,signal_number,stop_reason);CREATE TABLE pr_creations(stage,expected_head,number);')
  conn.execute('INSERT INTO runs VALUES(?,?,?,?,?,?,?,?)',(d.RUN,'blocked',d.AUTH,d.PIN,'issue43-one-shot-a2','/state/queue/'+d.QUEUE+'/bridge/worktrees/'+d.RUN,None,None))
  conn.execute('INSERT INTO failures VALUES(?,?,?,?,?,?)',('child_invocation','child_nonzero',1,None,22556,'exit_nonzero'))
 db.chmod(0o600);return db


def test_exact_consumed_database_readonly_projection_and_no_raw_text():
 with tempfile.TemporaryDirectory(dir=Path.home()) as folder:
  root=Path(folder)/d.QUEUE;db=dbfixture(root);before=db.read_bytes()
  result=d.inspect_queue(root,uid=os.geteuid())
  assert result['bridge']['failure']['exit_code']==1 and result['retry'] is False
  assert db.read_bytes()==before and not Path(str(db)+'-wal').exists()
  entry=json.loads((root/'state.json').read_text());entry['invocations']=2;(root/'state.json').write_text(json.dumps(entry))
  with pytest.raises(d.Stop):d.inspect_queue(root,uid=os.geteuid())


def test_database_sidecar_and_forged_run_refuse():
 with tempfile.TemporaryDirectory(dir=Path.home()) as folder:
  root=Path(folder)/d.QUEUE;db=dbfixture(root)
  Path(str(db)+'-wal').touch()
  with pytest.raises(d.Stop,match='SIDECAR'):d.inspect_queue(root,uid=os.geteuid())
  Path(str(db)+'-wal').unlink()
  with sqlite3.connect(db) as conn:conn.execute("UPDATE runs SET run_id=?",('a'*32,))
  with pytest.raises(d.Stop,match='IDENTITY'):d.inspect_queue(root,uid=os.geteuid())
