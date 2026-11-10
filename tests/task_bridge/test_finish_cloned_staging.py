import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile

import pytest
from test_operator_bootstrap import compose_record

ROOT=Path(__file__).resolve().parents[2]


def load(file):
    spec=importlib.util.spec_from_file_location(file[:-3],ROOT/'ops/bridge_one_shot'/file)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def git(*args):return subprocess.check_output(['git',*map(str,args)],stderr=subprocess.DEVNULL)


@pytest.fixture
def checkpoint(monkeypatch):
    if os.geteuid()!=0:pytest.skip('actual root/worker ownership is required')
    with tempfile.TemporaryDirectory(dir=Path.home()) as directory:
        root=Path(directory);root.chmod(0o700)
        m=load('operator_bootstrap_v4.py');workspace=root/'workspace';workspace.mkdir(mode=0o700)
        tree=root/'public-tree';tree.mkdir(mode=0o700)
        git('-C',tree,'init','-q');git('-C',tree,'config','user.name','Offline');git('-C',tree,'config','user.email','offline@example.invalid')
        (tree/'README').write_text('public base\n');git('-C',tree,'add','.');git('-C',tree,'commit','-qm','base')
        base=git('-C',tree,'rev-parse','HEAD').strip()
        (tree/'requirements.txt').write_bytes((ROOT/'requirements.txt').read_bytes())
        git('-C',tree,'add','.');git('-C',tree,'commit','-qm','candidate')
        pin=git('-C',tree,'rev-parse','HEAD').decode().strip()
        for name in m.ARTIFACTS-{'ops/bridge_one_shot/operator_artifacts.json'}:
            target=tree/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((ROOT/name).read_bytes())
        (tree/'ops/bridge_one_shot/operator_artifacts.json').write_text(json.dumps({'schema':1,'runner_commit':pin,'files':sorted(m.ARTIFACTS)}))
        git('-C',tree,'add','.');git('-C',tree,'commit','-qm','adapter')
        merge=git('-C',tree,'rev-parse','HEAD').decode().strip();source=root/'source.git'
        git('clone','--bare','-q',tree,source);source.chmod(0o700)
        branch=git('--git-dir='+str(source),'symbolic-ref','HEAD').decode().strip()
        git('--git-dir='+str(source),'update-ref',branch,base.decode())
        m.RUNNER_PIN=pin;m.MERGE=merge;m.SIGNER_STATE=str(root/'claims')
        attempt=m.PREFIX_ATTEMPT
        cfg={key:str(workspace/(attempt+'-'+key)) for key in m.PREFIX_KEYS}
        cfg.update(source=str(source),merge=merge,image='sha256:'+'a'*64,uid=10000,gid=10000,
          attempt=attempt,overall_seconds=1800,signer_state_root=m.SIGNER_STATE,
          signer_key=str(workspace/'manager-key.pem'),signer_public=str(workspace/'manager-public.pem'),
          signer_token=str(workspace/'root-github-token'),signer_policy=str(workspace/(attempt+'-signer-policy.json')),
          plan=str(workspace/(attempt+'-operator-plan.json')),venv=str(root/'venv'),
          task_body_sha256=m.TASK_DIGEST,requirements_sha256=hashlib.sha256((ROOT/'requirements.txt').read_bytes()).hexdigest(),
          python_version='3.14.9',pytest_version='8.3.3',test_python='/reviewed/bin/python',
          start='2026-11-10T00:00:00Z',cursors={'41':1,'45':2},git_name='Offline Worker',
          git_email='offline@example.invalid',excluded_roots=[str(tree)])
        for key in m.PREFIX_KEYS:
            p=Path(cfg[key]);p.mkdir(mode=0o700)
            if key in ('state','auth','context','home','inbox'):os.chown(p,10000,10000)
        queue=Path(cfg['state'])/'queue';queue.mkdir(mode=0o700);os.chown(queue,10000,10000)
        Path(m.SIGNER_STATE).mkdir(mode=0o700)
        venv=Path(cfg['venv']);venv.mkdir(mode=0o700);os.chown(venv,10000,10000)
        (venv/'pyvenv.cfg').write_text('offline metadata');os.chown(venv/'pyvenv.cfg',10000,10000)
        for key in ('signer_key','signer_token','signer_public'):
            p=Path(cfg[key]);p.write_bytes(b'-----BEGIN PUBLIC KEY-----\nOFFLINE\n' if key=='signer_public' else b'OFFLINE_NEVER_READ');p.chmod(0o600)
        prefix_intent=workspace/(attempt+'-prefix-completion-intent.json')
        m._write(prefix_intent,{'schema':1,'purpose':'complete-empty-pre-runtime-prefix','attempt':attempt,'activation':False},0,0)
        blobs={name:git('--git-dir='+str(source),'show',merge+':'+name) for name in m.ARTIFACTS}
        for name,blob in blobs.items():
            path=Path(cfg['bundle'])/Path(name).name;m._write(path,blob,0,0)
            if path.name in ('worker_probe.py','connect_proxy.py'):path.chmod(0o444)
        m._write(Path(cfg['bundle'])/'merged-byte-manifest.json',{'schema':1,'merge':merge,'sha256':{name:hashlib.sha256(blob).hexdigest() for name,blob in blobs.items()}},0,0)
        git('clone','--no-local','--no-checkout','-q',source,cfg['runner'])
        assert subprocess.run(['git','-C',cfg['runner'],'cat-file','-e',pin+'^{commit}'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode!=0
        original=m._bounded_run;calls=[]
        def bounded(argv,**kwargs):
            calls.append(tuple(argv))
            if argv[0]=='docker':
                if argv[:3]==['docker','image','inspect']:
                    return (cfg['image']+'\n').encode() if argv[4]=='{{.Id}}' else b'PATH\nHOME\n\n'
                if argv[:2]==['docker','compose']:return json.dumps(compose_record(cfg)).encode()
                return b''
            return original(argv,**kwargs)
        monkeypatch.setattr(m,'_bounded_run',bounded)
        yield m,cfg,workspace,calls


def test_actual_root_git_completion_preserves_refs_source_and_transfers_last(checkpoint,monkeypatch):
    m,cfg,workspace,calls=checkpoint
    source=m._git_snapshot(Path(cfg['source']));runner=m._git_snapshot(Path(cfg['runner'])/'.git')
    assert source[0] and runner[0] and source[1]==runner[1]
    transfer=m._chown_fresh_tree;transferred=[]
    def chown(path,uid,gid):
        assert m._git_snapshot(Path(cfg['source']))==source
        now=m._git_snapshot(Path(cfg['runner'])/'.git')
        assert now[0]==runner[0] and now[2]==runner[2]
        assert now[1]==m.RUNNER_PIN.encode()+b'\n'
        transferred.append(len(calls));transfer(path,uid,gid)
    monkeypatch.setattr(m,'_chown_fresh_tree',chown)
    assert m.stage(cfg,cloned_checkpoint=True).startswith('STAGED ONLY')
    assert len(transferred)==1 and all(a[0] not in ('git','/usr/bin/git') for a in calls[transferred[0]:])
    assert Path(cfg['runner']).stat().st_uid==10000
    assert (Path(cfg['runner'])/'.git/HEAD').read_bytes()==m.RUNNER_PIN.encode()+b'\n'
    assert not (Path(cfg['runner'])/'.git/FETCH_HEAD').exists()
    assert (workspace/(m.PREFIX_ATTEMPT+'-git-completion-intent.json')).exists()
    handoff=Path(cfg['plan']).parent/(Path(cfg['plan']).stem+'-handoff.json')
    assert json.loads(handoff.read_text())['activation']=='NO-GO'
    assert json.loads(handoff.read_text())['timer']=='DISABLED'
    assert list(Path(cfg['signer_state_root']).iterdir())==[]
    assert all('up' not in a and '--execute' not in a and 'reset' not in a and 'clean' not in a for a in calls)


@pytest.mark.parametrize('case',['extra_ref','changed_ref','file','index','claim','intent','active_hook','config','bundle'])
def test_ambiguous_checkpoint_stops_before_object_transfer(checkpoint,case):
    m,cfg,workspace,calls=checkpoint;store=Path(cfg['runner'])/'.git'
    if case=='extra_ref':git('--git-dir='+str(store),'update-ref','refs/heads/historical',git('--git-dir='+str(store),'rev-parse','HEAD').decode().strip())
    elif case=='changed_ref':
        source=Path(cfg['source']);ref=git('--git-dir='+str(source),'symbolic-ref','HEAD').decode().strip()
        git('--git-dir='+str(source),'update-ref',ref,m.RUNNER_PIN)
    elif case=='file':(Path(cfg['runner'])/'preserve').write_text('public fixture')
    elif case=='index':(store/'index').touch()
    elif case=='claim':(Path(cfg['signer_state_root'])/'historical.json').write_text('preserve')
    elif case=='intent':(workspace/(m.PREFIX_ATTEMPT+'-git-completion-intent.json')).touch()
    elif case=='active_hook':(store/'hooks/post-checkout').write_text('OFFLINE_NEVER_RUN')
    elif case=='config':git('--git-dir='+str(store),'config','core.fsmonitor','OFFLINE_NEVER_RUN')
    else:(Path(cfg['bundle'])/'worker_probe.py').chmod(0o600)
    calls.clear()
    with pytest.raises((ValueError,RuntimeError,PermissionError,FileExistsError)):
        m.stage(cfg,cloned_checkpoint=True)
    assert not any('fetch' in a for a in calls)
    assert not Path(cfg['plan']).exists()


def test_local_git_options_disable_network_credentials_hooks_and_maintenance(monkeypatch):
    m=load('operator_bootstrap_v4.py');seen=[]
    def run(argv,**kwargs):seen.append((argv,kwargs));return b'commit\n'
    monkeypatch.setattr(m,'_bounded_run',run)
    assert m._local_git(Path('/synthetic/source.git'),('cat-file','-t',m.RUNNER_PIN))==b'commit\n'
    argv,opts=seen[0]
    assert 'protocol.allow=never' in argv and 'protocol.file.allow=always' in argv
    assert 'core.hooksPath=/dev/null' in argv and 'credential.helper=' in argv
    assert 'maintenance.auto=false' in argv and opts['env']['GIT_NO_LAZY_FETCH']=='1'
    assert opts['env']['HOME']=='/nonexistent'


def test_source_hash_checked_and_private_exception_values_suppressed(monkeypatch,capsys):
    import sys
    m=load('finish_cloned_staging.py')
    with pytest.raises(m.Stop,match='SOURCE_DIGEST'):
        m.load_public('a'*40,'operator_bootstrap_v4.py',lambda *_:b'changed code')
    monkeypatch.setattr(sys,'argv',['finish','--workspace','/synthetic','--source-commit','a'*40,'--complete'])
    def fail(*a,**k):raise RuntimeError('OFFLINE_SECRET /synthetic/private')
    monkeypatch.setattr(m,'complete',fail)
    assert m.main()==1
    out=capsys.readouterr().out
    assert 'TYPE=RuntimeError' in out and 'OFFLINE_SECRET' not in out and '/synthetic/private' not in out


def test_documented_loader_syntax_and_digest_order():
    import ast
    doc=(ROOT/'ops/bridge_one_shot/FINISH_CLONED_STAGING.md').read_text()
    block=doc.split('```bash\n',1)[1].split('```',1)[0]
    subprocess.run(['bash','-n'],input=block.encode(),check=True)
    code=block.split("<<'PY'\n",1)[1].rsplit('\nPY',1)[0]
    ast.parse(code)
    assert code.index('hashlib.sha256(source)')<code.index('exec(compile(source')
