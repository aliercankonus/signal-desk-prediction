import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import pytest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'autonomous-development'))
spec=importlib.util.spec_from_file_location('queued_write_root',ROOT/'ops/github_inbox/queued_write_root.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def git(*a):return subprocess.check_output(['git',*map(str,a)],stderr=subprocess.DEVNULL).decode().strip()


def test_root_comes_from_a_real_bridge_queue_entry_not_the_wrong_global_path(monkeypatch):
    from bridge_queue import BridgeQueue
    from queue_store import TaskStore
    with tempfile.TemporaryDirectory(dir=Path.home()) as d:
        parent=Path(d);parent.chmod(0o700);source=parent/'source';source.mkdir(mode=0o700)
        git('-C',source,'init','-q','-b','main')
        (source/'requirements.txt').write_text('pytest==8.3.3\n')
        git('-C',source,'add','requirements.txt')
        git('-C',source,'-c','user.name=Offline','-c','user.email=offline@example.invalid','commit','-qm','fixture')
        commit=git('-C',source,'rev-parse','HEAD')
        git('-C',source,'remote','add','origin','https://github.com/aliercankonus/signal-desk-prediction.git')
        auth=parent/'authorization.json';auth.write_text(json.dumps(dict(repo='aliercankonus/signal-desk-prediction',issue=43,
            body_digest='a'*64,base=commit,branch='issue43-fixture')));auth.chmod(0o600)
        ctx_dir=parent/'context';ctx_dir.mkdir(mode=0o700);ctx=ctx_dir/'context.json'
        ctx.write_text(json.dumps(dict(test_python=sys.executable,requirements_sha256=hashlib.sha256((source/'requirements.txt').read_bytes()).hexdigest(),
            runner_commit=commit,python_version='3.12.1',pytest_version='8.3.3')));ctx.chmod(0o600)
        queue=parent/'queue';owner=BridgeQueue(TaskStore(queue))
        entry=owner.enqueue(source,auth,ctx,runner_commit=commit)
        actual=Path(entry['bridge_state'])/'worktrees'/entry['bridge_run_id']
        monkeypatch.setenv('HERMES_WRITE_SAFE_ROOT','/state/worktrees')
        assert not actual.is_relative_to(Path(os.environ['HERMES_WRITE_SAFE_ROOT']))
        before={p.name:p.read_bytes() for p in (queue/entry['id']).iterdir() if p.is_file()}
        with m.child_write_root(entry,queue=queue) as root:
            assert root==str(actual) and os.environ['HERMES_WRITE_SAFE_ROOT']==str(actual)
            assert not (queue/'other'/'bridge').is_relative_to(Path(root))
        assert os.environ['HERMES_WRITE_SAFE_ROOT']=='/state/worktrees'
        assert all((queue/entry['id']/name).read_bytes()==data for name,data in before.items())
        assert owner.store.load(entry['id'])['invocations']==0


@pytest.mark.parametrize('key,value',[('id','../escape'),('bridge_run_id','bad'),('kind','other'),('bridge_state','/state/queue/unrelated/bridge')])
def test_foreign_mapping_is_rejected_without_changing_environment(monkeypatch,key,value):
    entry=dict(id='a'*32,bridge_run_id='b'*32,kind='bridge',bridge_state='/state/queue/'+'a'*32+'/bridge')
    entry[key]=value;monkeypatch.setenv('HERMES_WRITE_SAFE_ROOT','preserve')
    with pytest.raises(ValueError):
        with m.child_write_root(entry):pytest.fail('must not enter')
    assert os.environ['HERMES_WRITE_SAFE_ROOT']=='preserve'


def test_dormant_factory_scopes_once_and_restores_after_child_exception(monkeypatch):
    from bridge_queue import BridgeQueue
    entry=dict(id='a'*32,bridge_run_id='b'*32,kind='bridge',bridge_state='/state/queue/'+'a'*32+'/bridge')
    calls=[]
    class Bridge:
        def once(self):calls.append(os.environ.get('HERMES_WRITE_SAFE_ROOT'));raise RuntimeError('simulated child failure')
    monkeypatch.setattr(BridgeQueue,'production_bridge',lambda *a:Bridge())
    monkeypatch.delenv('HERMES_WRITE_SAFE_ROOT',raising=False)
    bridge=m.production_bridge(entry,None)
    assert not calls and 'HERMES_WRITE_SAFE_ROOT' not in os.environ
    with pytest.raises(RuntimeError):bridge.once()
    assert calls==[entry['bridge_state']+'/worktrees/'+entry['bridge_run_id']]
    assert 'HERMES_WRITE_SAFE_ROOT' not in os.environ
