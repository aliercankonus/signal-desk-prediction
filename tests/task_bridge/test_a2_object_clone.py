import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import pytest

ROOT=Path(__file__).resolve().parents[2]
sp=importlib.util.spec_from_file_location('object_clone',ROOT/'ops/bridge_one_shot/prepare_a2_object_clone.py')
m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m)


def git(*args,check=True):
    p=subprocess.run(['git',*map(str,args)],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
    if check:p.check_returncode()
    return p


def store(tmp_path):
    seed=tmp_path/'seed';git('init',seed);git('-C',seed,'config','user.name','Offline');git('-C',seed,'config','user.email','offline@example.invalid')
    (seed/'file').write_text('fixture\n');git('-C',seed,'add','file');git('-C',seed,'commit','-m','fixture')
    pin=git('-C',seed,'rev-parse','HEAD').stdout.decode().strip()
    source=tmp_path/'source';git('init','--bare',source)
    git('--git-dir='+str(source),'fetch','--no-write-fetch-head',seed,pin)
    return source,pin


def test_real_object_only_store_reproduces_old_failure_and_new_clone_passes(tmp_path):
    source,pin=store(tmp_path)
    assert not git('--git-dir='+str(source),'for-each-ref').stdout
    old=tmp_path/'old';git('clone','--no-local','--no-checkout','--no-hardlinks',source,old)
    assert git('-C',old,'checkout','--detach',pin,check=False).returncode==128
    before=m.refs(source);old_head=(old/'.git/HEAD').read_bytes()
    new=tmp_path/'new';m.clone_exact(source,new,pin=pin,uid=os.geteuid(),gid=os.getegid())
    assert git('-C',new,'rev-parse','HEAD').stdout.strip()==pin.encode()
    assert not git('-C',new,'status','--porcelain').stdout and not (new/'.git/FETCH_HEAD').exists()
    assert m.refs(source)==before and (old/'.git/HEAD').read_bytes()==old_head
    with pytest.raises(m.Stop,match='DESTINATION_EXISTS'):m.clone_exact(source,new,pin=pin)


def test_git_order_and_ownership_are_not_weakened(monkeypatch,tmp_path):
    source,pin=store(tmp_path);events=[];new=tmp_path/'new'
    def run(args):events.append(('git',str(args)));return m.git(args)
    monkeypatch.setattr(m.os,'chown',lambda *a:events.append(('chown',str(a[0]))))
    m.clone_exact(source,new,pin=pin,run=run)
    first=next(i for i,v in enumerate(events) if v[0]=='chown')
    assert all(v[0]=='git' for v in events[:first]) and all(v[0]=='chown' for v in events[first:])
    assert not any('safe.directory' in e[1] for e in events)
    assert any("'--no-write-fetch-head'" in e[1] and pin in e[1] for e in events)


def test_failed_fetch_preserves_clone_and_never_transfers_owner(monkeypatch,tmp_path):
    source,pin=store(tmp_path);new=tmp_path/'new'
    def run(args):
        if 'fetch' in args:raise TimeoutError('synthetic')
        return m.git(args)
    monkeypatch.setattr(m.os,'chown',lambda *a:pytest.fail('no transfer before verification'))
    with pytest.raises(TimeoutError):m.clone_exact(source,new,pin=pin,run=run)
    assert (new/'.git/HEAD').exists()
    with pytest.raises(m.Stop,match='DESTINATION_EXISTS'):m.clone_exact(source,new,pin=pin,run=run)


def prefix(root):
    for name in ('helpers','journals','state','state/queue','auth','inbox','runner','runner/.git'):(root/name).mkdir(mode=0o700)
    for name in ('stage-intent.json','signer-policy.json','auth/authorization.json','inbox/manager-public.pem','inbox/enrollment.json','helpers/auth.py','helpers/write_root.py','helpers/cleanup.py','helpers/diag.py','helpers/signer.py','helpers/readback.py','helpers/capture.py','helpers/factory.py','helpers/worker-preflight-v3.py','runner/.git/HEAD'):
        (root/name).write_text('public fixture');(root/name).chmod(0o600)
    (root/'auth/github-token').touch(mode=0o400)


def test_snapshot_refuses_symlinks_secret_store_and_nonempty_token(tmp_path):
    prefix(tmp_path);before=m.snapshot(tmp_path,root_uid=os.geteuid())
    (tmp_path/m.RECOVERY).mkdir();(tmp_path/m.RECOVERY/'new').write_text('excluded')
    assert m.snapshot(tmp_path,root_uid=os.geteuid())==before
    token=tmp_path/'auth/github-token';token.chmod(0o600);token.write_text('synthetic secret')
    with pytest.raises(m.Stop,match='TOKEN_NOT_EMPTY'):m.snapshot(tmp_path,root_uid=os.geteuid())
    token.write_text('');(tmp_path/'auth/auth-store.json').write_text('must not read')
    with pytest.raises(m.Stop,match='PREFIX_SUBTREE_INVENTORY'):m.snapshot(tmp_path,root_uid=os.geteuid())
    (tmp_path/'auth/auth-store.json').unlink();(tmp_path/'helpers/auth.py').unlink();(tmp_path/'helpers/auth.py').symlink_to('/etc/hostname')
    with pytest.raises(m.Stop,match='PREFIX_METADATA'):m.snapshot(tmp_path,root_uid=os.geteuid())


def test_default_entry_is_inert(monkeypatch,capsys):
    monkeypatch.setattr(sys,'argv',['entry']);monkeypatch.setattr(m,'prepare',lambda *a:pytest.fail('no prep'))
    assert m.main()==0 and 'REVIEW ONLY' in capsys.readouterr().out


def test_real_prepare_one_way_intent_and_prefix_preservation(monkeypatch):
    # Real private ancestry and production guards, current UID fixture only;
    # actual root-to-worker transfer remains an operator gate, not proven here.
    with tempfile.TemporaryDirectory(dir=Path.home()) as d:
        w=Path(d);w.chmod(0o700);root=w/m.ATTEMPT;root.mkdir(mode=0o700);prefix(root)
        (root/'stage-intent.json').write_text(json.dumps(dict(instruction_id=m.INSTRUCTION,policy=m.POLICY,retry=False)))
        (root/'auth/authorization.json').write_text(json.dumps(m.POLICY))
        source=w/'store';source.mkdir(mode=0o700)
        plan=w/(m.OLD+'-runtime-v2-plan.json');plan.write_text(json.dumps(dict(attempt=m.OLD,source=str(source),uid=os.geteuid(),gid=os.getegid())));plan.chmod(0o600)
        calls=[]
        def clone(source,dest,**kw):calls.append(dest);dest.mkdir();return {'refs_sha256':'a'*64,'files':{}}
        recovery=m.prepare(str(w),uid=os.geteuid(),gid=os.getegid(),root_uid=os.geteuid(),clone=clone)
        assert json.loads((recovery/'ready.json').read_text())['task'] is False
        assert (root/'runner/.git/HEAD').read_text()=='public fixture'
        with pytest.raises(FileExistsError):m.prepare(str(w),uid=os.geteuid(),gid=os.getegid(),root_uid=os.geteuid(),clone=clone)
        assert len(calls)==1 and not (root/'plan.json').exists()



def test_preparation_failure_preserves_intent_and_records_bounded_stage(monkeypatch):
    with tempfile.TemporaryDirectory(dir=Path.home()) as d:
        w=Path(d);w.chmod(0o700);root=w/m.ATTEMPT;root.mkdir(mode=0o700);prefix(root)
        (root/'stage-intent.json').write_text(json.dumps(dict(instruction_id=m.INSTRUCTION,policy=m.POLICY,retry=False)))
        (root/'auth/authorization.json').write_text(json.dumps(m.POLICY));source=w/'store';source.mkdir(mode=0o700)
        plan=w/(m.OLD+'-runtime-v2-plan.json');plan.write_text(json.dumps(dict(attempt=m.OLD,source=str(source),uid=os.geteuid(),gid=os.getegid())));plan.chmod(0o600)
        def fail(*a,**kw):raise TimeoutError('PRIVATE_DETAIL')
        with pytest.raises(TimeoutError):m.prepare(str(w),uid=os.geteuid(),gid=os.getegid(),root_uid=os.geteuid(),clone=fail)
        rec=json.loads((root/m.RECOVERY/'blocked.json').read_text())
        assert rec==dict(schema=1,stage='exact-object-clone',error_type='TimeoutError',retry=False)
        assert (root/m.RECOVERY/'intent.json').exists() and not (root/m.RECOVERY/'ready.json').exists()
        with pytest.raises(FileExistsError):m.prepare(str(w),uid=os.geteuid(),gid=os.getegid(),root_uid=os.geteuid(),clone=fail)


def test_report_one_post_readback_and_ambiguous_post_is_never_repeated(monkeypatch,tmp_path):
    ready=tmp_path/'ready.json';ready.write_text(json.dumps(dict(prepared_runner=True,task=False,runtime=False)))
    # Root ownership is an explicit seam; request validation/readback and the
    # real exclusive report-intent/fsync writer run unchanged with synthetic API.
    monkeypatch.setattr(m,'blob',lambda p,**kw:p.read_bytes())
    seen=[];posted=[]
    def request(method,path,data=None):
        seen.append((method,path))
        if method=='POST':posted.append(data['body']);return {'id':7000000001}
        return dict(id=7000000001,body=posted[0],issue_url='https://api.github.com/repos/'+m.REPO+'/issues/41')
    assert m.report('/unused',tmp_path,request)==7000000001
    assert [x[0] for x in seen]==['POST','GET']
    with pytest.raises(FileExistsError):m.report('/unused',tmp_path,request)
    assert len(seen)==2
    other=tmp_path/'other';other.mkdir();(other/'ready.json').write_bytes(ready.read_bytes())
    def lost(*a):raise TimeoutError('lost reply')
    with pytest.raises(TimeoutError):m.report('/unused',other,lost)
    with pytest.raises(FileExistsError):m.report('/unused',other,lost)


def test_durable_loader_syntax_and_hash_binding():
    import ast
    text=(ROOT/'ops/bridge_one_shot/RECOVER_A2_OBJECT_CLONE.md').read_text()
    block=text.split('```bash\n',1)[1].split('\n```',1)[0]
    subprocess.run(['bash','-n'],input=block.encode(),check=True)
    embedded=block.split("python3 -I -B -c '\n",1)[1].split("\n' \"$RECOVERY_WORKSPACE\"",1)[0]
    tree=ast.parse(embedded)
    constants={n.targets[0].id:n.value.value for n in tree.body if isinstance(n,ast.Assign) and isinstance(n.targets[0],ast.Name) and isinstance(n.value,ast.Constant)}
    assert constants['expected']==hashlib.sha256((ROOT/'ops/bridge_one_shot/prepare_a2_object_clone.py').read_bytes()).hexdigest()
    assert constants['commit']=='08cb8d9a965c5dce4211c88126cf203b4a63f8a9'
