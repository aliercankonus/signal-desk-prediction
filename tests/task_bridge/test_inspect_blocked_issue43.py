import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
from types import SimpleNamespace
import pytest

ROOT=Path(__file__).resolve().parents[2]
s=importlib.util.spec_from_file_location('blocked_inspection',ROOT/'ops/bridge_one_shot/inspect_blocked_issue43.py')
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)


def db_fixture(parent):
    path=parent/'journal.sqlite3'
    with sqlite3.connect(path) as c:
        c.execute('CREATE TABLE runs(run_id,status,auth_identity,base,branch,worktree,head,pr_url)')
        c.execute('CREATE TABLE failures(stage,category,exit_code,signal_number,duration_ms,stop_reason)')
        c.execute('CREATE TABLE stage_events(id,stage,duration_ms,exit_code,signal_number,stop_reason)')
        c.execute('CREATE TABLE pr_creations(stage,expected_head,number)')
        c.execute('INSERT INTO runs VALUES (?,?,?,?,?,?,?,?)',(m.RUN,'blocked',m.AUTH,m.PIN,
            'issue43-one-shot-review-note','/state/queue/'+m.QUEUE+'/bridge/worktrees/'+m.RUN,None,None))
        c.execute('INSERT INTO stage_events VALUES (1,?,?,?,?,?)',('child_invocation',None,None,None,None))
        c.execute('INSERT INTO failures VALUES (?,?,?,?,?,?)',('child_invocation','child_nonzero',1,None,9012,'exit_nonzero'))
    path.chmod(0o600);return path


def test_real_sqlite_diagnostics_are_read_only_and_exclude_private_strings():
    with tempfile.TemporaryDirectory(dir=Path.home()) as d:
        parent=Path(d);parent.chmod(0o700);path=db_fixture(parent)
        before={p.name:p.read_bytes() for p in parent.iterdir()}
        result,worktree=m.database(path,uid=os.geteuid())
        assert result['failure']==dict(stage='child_invocation',category='child_nonzero',exit_code=1,signal=None,duration_ms=9012,stop_reason='exit_nonzero')
        assert worktree.startswith('/state/queue/') and not worktree.startswith('/state/worktrees/')
        assert all((parent/name).read_bytes()==data for name,data in before.items())
        assert set(before)=={p.name for p in parent.iterdir()}
        with sqlite3.connect(path) as c:
            c.execute("UPDATE failures SET category='SECRET_FAILURE_TEXT',stop_reason='SECRET_PROVIDER_OUTPUT',exit_code=-123")
        result,_=m.database(path,uid=os.geteuid())
        assert 'SECRET' not in json.dumps(result) and result['failure']['exit_code'] is None
        assert result['failure']['category']==result['failure']['stop_reason']=='UNVERIFIED'


@pytest.mark.parametrize('change',['identity','sidecar','view','bound','symlink'])
def test_untrusted_or_live_sqlite_is_refused_without_writes(change):
    with tempfile.TemporaryDirectory(dir=Path.home()) as d:
        parent=Path(d);parent.chmod(0o700);path=db_fixture(parent)
        if change=='sidecar':Path(str(path)+'-wal').write_bytes(b'preserve')
        elif change=='symlink':
            real=parent/'original';path.rename(real);path.symlink_to(real)
        else:
            with sqlite3.connect(path) as c:
                if change=='identity':c.execute("UPDATE runs SET run_id='other'")
                elif change=='view':c.execute('DROP TABLE failures');c.execute("CREATE VIEW failures AS SELECT 'secret' AS stage")
                else:
                    c.executemany('INSERT INTO stage_events VALUES (?,?,?,?,?,?)',[(i,'preflight',None,None,None,None) for i in range(2,35)])
        before={p.name:p.read_bytes() for p in parent.iterdir() if p.is_file()}
        with pytest.raises(m.Stop):m.database(path,uid=os.geteuid())
        assert all((parent/name).read_bytes()==data for name,data in before.items())


def test_one_report_intent_precedes_post_and_ambiguous_failure_cannot_repeat(tmp_path):
    posts=[];text='{"diagnostic":"fixed-safe-fields"}'
    class Client:
        def publish(self,issue,body):
            assert (tmp_path/(m.ATTEMPT+'-issue43-diagnostic-report')).exists()
            posts.append(body);return 123
        def comment(self,issue,ident):raise RuntimeError('PRIVATE_ERROR')
    with pytest.raises(RuntimeError):m.report(tmp_path,{},text,client=Client())
    with pytest.raises(FileExistsError):m.report(tmp_path,{},text,client=Client())
    assert posts==[text]
    assert not (tmp_path/(m.ATTEMPT+'-issue43-diagnostic-report-receipt')).exists()


def test_successful_report_has_exact_readback_receipt_and_remains_no_replay(tmp_path):
    text='{"diagnostic":"fixed-safe-fields"}'
    class Client:
        def publish(self,issue,body):assert issue==41 and body==text;return 123
        def comment(self,issue,ident):return dict(id=ident,body=text,issue_url='https://api.github.com/repos/aliercankonus/signal-desk-prediction/issues/41')
    assert m.report(tmp_path,{},text,client=Client())==123
    assert json.loads((tmp_path/(m.ATTEMPT+'-issue43-diagnostic-report-receipt')).read_text())['verified']
    with pytest.raises(FileExistsError):m.report(tmp_path,{},text,client=Client())


def test_actual_root_admits_only_exact_run_and_redacts_checkpoint_private_fields():
    if os.geteuid()!=0:pytest.skip('actual root/worker ownership in CI')
    with tempfile.TemporaryDirectory(dir=Path.home()) as d:
        w=Path(d);w.chmod(0o700);state=w/(m.ATTEMPT+'-state');state.mkdir(mode=0o700)
        for p in (state,state/'queue',state/'queue'/m.QUEUE,state/'queue'/m.QUEUE/'bridge'):
            if not p.exists():p.mkdir(mode=0o700)
            os.chown(p,10000,10000)
        bridge=state/'queue'/m.QUEUE/'bridge';db=db_fixture(bridge);os.chown(db,10000,10000)
        journal=w/(m.ATTEMPT+'-journal_parent');journal.mkdir(mode=0o700);attempt=journal/(m.ATTEMPT+'-issue43-once');attempt.mkdir(mode=0o700)
        plan=dict(state=str(state),bundle=str(w/(m.ATTEMPT+'-runtime-v2-bundle')),
            signer_token=str(w/'root-github-token'),journal_parent=str(journal),merge='42db985bba2f0a64ce8d848e39a11c2a18c689f3',uid=10000,gid=10000,attempt=m.ATTEMPT)
        def write(path,data,uid=0):path.write_text(json.dumps(data));path.chmod(0o600);os.chown(path,uid,uid)
        write(w/(m.ATTEMPT+'-runtime-v2-plan.json'),plan)
        write(attempt/'phase.json',dict(attempt=m.ATTEMPT,phase='blocked',status='blocked',intent=None,unresolved_effect='one_bridge_claim',cleanup_verified=False))
        write(attempt/'compose.issue43-once.json',dict(services={'inbox-worker':{'environment':{'HERMES_WRITE_SAFE_ROOT':'/state/worktrees','PRIVATE':'NEVER_PUBLISH'}}}))
        write(state/'queue'/m.QUEUE/'state.json',dict(id=m.QUEUE,bridge_run_id=m.RUN,authorization_identity=m.AUTH,status='blocked',invocations=1,failure_code='bridge',private='NEVER_PUBLISH'),10000)
        write(bridge/'recovery-checkpoint.json',dict(identity={'run_id':m.RUN},stage='child-intent',last_confirmed='worktree-created',remaining='NEVER_PUBLISH',session='NEVER_PUBLISH'),10000)
        _,_,text=m.inspect(str(w));result=json.loads(text)
        assert not result['write_root_contains_worktree']
        assert result['bridge']['failure']['category']=='child_nonzero'
        assert 'NEVER_PUBLISH' not in text and str(w) not in text and len(text.encode())<=2048
        # Inspect never opens the reporting credential: it is deliberately absent.
        assert not Path(plan['signer_token']).exists()
        assert set(w.iterdir())=={state,journal,w/(m.ATTEMPT+'-runtime-v2-plan.json')}


def test_root_entry_has_no_runtime_or_raw_exception_output():
    import ast
    tree=ast.parse((ROOT/'ops/bridge_one_shot/inspect_blocked_issue43.py').read_text())
    imports={n.name for node in ast.walk(tree) if isinstance(node,ast.Import) for n in node.names}
    assert 'subprocess' not in imports
    assert m.enum('PRIVATE',m.STAGES)=='UNVERIFIED' and m.number(True) is None
