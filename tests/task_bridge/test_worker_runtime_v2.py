import dataclasses
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


def load(path,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m


c=load('ops/github_inbox/worker_credential.py','credential_v2')
p=load('ops/bridge_one_shot/prepare_worker_runtime_v2.py','prepare_v2')
h=load('ops/bridge_one_shot/operator_host_v2.py','host_v2')
TOKEN=b'github_pat_'+b'OFFLINE_FIXTURE_ONLY_'*3


@pytest.mark.parametrize('suffix',[b'',b'path=aliercankonus/signal-desk-prediction\n',b'path=aliercankonus/signal-desk-prediction.git\n'])
def test_closed_credential_get_supports_frozen_rest_and_git(suffix):
    assert c.credential('get',b'protocol=https\nhost=github.com\n'+suffix+b'\n',lambda:TOKEN)==b'username=x-access-token\npassword='+TOKEN+b'\n\n'


@pytest.mark.parametrize('record',[b'protocol=http\nhost=github.com\n',b'protocol=https\nhost=evil.invalid\n',
    b'protocol=https\nhost=github.com:443\n',b'protocol=https\nhost=github.com\npath=other/repo\n',
    b'protocol=https\nhost=github.com\npath=aliercankonus/signal-desk-prediction/../other\n',
    b'protocol=https\nhost=github.com\nhost=evil.invalid\n',b'protocol=https\nhost=github.com\npassword=private\n',
    b'protocol=https\nhost=github.com\nusername=unexpected\n',b'x'*4097,b'\0'])
def test_scope_failure_never_reads_secret(record):
    def forbidden():raise AssertionError('credential read')
    with pytest.raises(ValueError):c.credential('get',record,forbidden)


@pytest.mark.parametrize('op',['store','erase'])
def test_credential_mutations_are_noop_without_secret_read(op):
    def forbidden():raise AssertionError('credential read')
    assert c.credential(op,b'password=UNRELATED_PRIVATE_INPUT\n',forbidden)==b''


def test_error_output_does_not_echo_private_protocol():
    child=subprocess.run([sys.executable,'-I','-B',str(ROOT/'ops/github_inbox/worker_credential.py'),'get'],
        input=b'protocol=https\nhost=github.com\npassword=DO_NOT_ECHO_THIS\n\n',capture_output=True,timeout=10)
    assert child.returncode==1 and child.stdout==b'' and child.stderr==b'worker credential unavailable\n'


def test_v2_inventory_and_versioned_byte_manifest():
    release=json.loads((ROOT/'ops/bridge_one_shot/runtime_v2_release.json').read_text())
    assert hashlib.sha256((ROOT/'ops/bridge_one_shot/runtime_v2_release.json').read_bytes()).hexdigest()==p.RELEASE_HASH
    assert set(release['files'])==h.ARTIFACTS
    for path,digest in release['files'].items():assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==digest
    assert json.loads((ROOT/'ops/bridge_one_shot/operator_artifacts_v2.json').read_text())==dict(schema=2,runner_commit=h.RUNNER_PIN,files=sorted(h.ARTIFACTS))


def test_owner_check_precedes_provider_handoff_and_credential_use(monkeypatch):
    from test_operator_host import plan, FakeRunner
    events=[];ops=h.HostOperations(plan(),runner=FakeRunner(),pause=lambda *a:events.append('provider'))
    def worker(*args,**kw):
        events.append(args)
        return json.dumps(dict(worker_owner_git=True,credential_helper_configured=True))
    ops._worker=worker;ops.login()
    assert events[0][3]=='/opt/worker-preflight.py' and events[1]=='provider'
    events.clear();ops._worker=lambda *a,**kw:json.dumps(dict(worker_owner_git=False,credential_helper_configured=True))
    with pytest.raises(ValueError):ops.login()
    assert not events


def test_common_private_parent_is_not_mistaken_for_a_worker_mount():
    from test_operator_host import plan
    q=plan();root=Path('/private-workspace')
    q=dataclasses.replace(q,signer_token=root/'token',signer_key=root/'key',signer_public=root/'public',
                          signer_policy=root/'scope',runner=root/'runner')
    assert all(not (x==q.runner or x in q.runner.parents or q.runner in x.parents) for x in h.protected_locations(q))
    unsafe=dataclasses.replace(q,signer_key=q.runner/'key')
    assert any(q.runner in x.parents for x in h.protected_locations(unsafe))


@pytest.fixture
def prepared_root():
    if os.geteuid()!=0:pytest.skip('actual protected root/worker filesystem requires root CI')
    boot=load('ops/bridge_one_shot/operator_bootstrap_v5.py','boot_v2_fixture')
    probe=load('ops/bridge_one_shot/probe_worker_runtime.py','probe_v2_fixture')
    with tempfile.TemporaryDirectory(dir=Path.home()) as folder:
        root=Path(folder);root.chmod(0o700);w=root/'workspace';w.mkdir(mode=0o700)
        tree=root/'tree';tree.mkdir(mode=0o700)
        release=json.loads((ROOT/'ops/bridge_one_shot/runtime_v2_release.json').read_text())
        def git(*args):return subprocess.check_output(['git',*map(str,args)],stderr=subprocess.DEVNULL)
        git('-C',tree,'init','-q')
        for path in release['files']:
            target=tree/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((ROOT/path).read_bytes())
        git('-C',tree,'add','.');git('-C',tree,'-c','user.name=Offline','-c','user.email=offline@example.invalid','commit','-qm','fixture')
        commit=git('-C',tree,'rev-parse','HEAD').decode().strip();source=root/'source'
        git('clone','--bare','-q',tree,source);source.chmod(0o700)
        cfg=dict(attempt=p.ATTEMPT,source=str(source),start='unchanged',cursors={'41':1,'45':2},
                 task_body_sha256=boot.TASK_DIGEST,merge=boot.MERGE,
                 test_python='/reviewed/bin/python',requirements_sha256='a'*64,python_version='3.14.9',pytest_version='8.3.3')
        for key in boot.PLAN_KEYS:
            if key not in cfg:cfg[key]=str(w/('old-'+key))
        cfg.update(uid=10000,gid=10000,overall_seconds=1800,image='sha256:'+'a'*64)
        for key in ('state','auth','home','journal_parent','signer_state_root'):
            target=Path(cfg[key]);target.mkdir(mode=0o700)
            if key in ('state','auth','home'):os.chown(target,10000,10000)
        queue=Path(cfg['state'])/'queue';queue.mkdir(mode=0o700);os.chown(queue,10000,10000)
        boot._write(w/'manager-public.pem',b'OFFLINE PUBLIC FIXTURE',0,0)
        boot._write(w/'worker-github-token',TOKEN,0,0)
        records=boot.build_records(cfg,b'OFFLINE PUBLIC FIXTURE')
        boot._write(Path(cfg['auth'])/'authorization.json',records['authorization.json'],10000,10000)
        boot._write(Path(cfg['home'])/'config.yaml',records['provider-config.yaml'],10000,10000)
        result=dict(schema=1,worker_identity=True,git_available=True,gh_available=False,hermes_available=True,
                    runner_head=True,runner_clean=True,test_versions=['3.14.9','8.3.3'],versions_match=True,capability_pass=False)
        boot._write(w/(p.ATTEMPT+'-runtime-probe-01-receipt.json'),dict(schema=1,probe=p.ATTEMPT+'-runtime-probe-01',
                    cleanup_verified=True,interrupted_or_error=False,credentials_installed=False,task_authority=False,result=result),0,0)
        yield probe,boot,w,cfg,release,commit


def test_actual_root_version_transition_preserves_old_state_and_credential_source(prepared_root):
    probe,boot,w,cfg,release,commit=prepared_root
    old={f:f.read_bytes() for f in w.rglob('*') if f.is_file()}
    get=lambda sha,path:(ROOT/path).read_bytes()
    p.provision(probe,boot,w,cfg,release,commit,apply=True,getter=get,source_fetch=lambda *a:None)
    assert all(f.read_bytes()==data for f,data in old.items())
    new=w/(p.ATTEMPT+'-runtime-v2-auth')/'github-token'
    assert new.read_bytes()==TOKEN and new.stat().st_uid==10000 and new.stat().st_gid==10000 and new.stat().st_mode&0o777==0o400
    plan=json.loads((w/(p.ATTEMPT+'-runtime-v2-plan.json')).read_text())
    assert plan['merge']==commit and plan['runner']==cfg['runner'] and plan['signer_policy']==cfg['signer_policy']
    with pytest.raises(p.Stop,match='ALREADY_PRESENT'):p.provision(probe,boot,w,cfg,release,commit,apply=True,getter=get)


def test_existing_state_blocks_before_intent_or_credential_copy(prepared_root):
    probe,boot,w,cfg,release,commit=prepared_root
    (Path(cfg['state'])/'queue'/'history').touch()
    with pytest.raises(p.Stop,match='EXISTING_RUNTIME'):p.provision(probe,boot,w,cfg,release,commit,apply=True)
    assert not (w/(p.ATTEMPT+'-runtime-v2-intent.json')).exists()


def test_source_ref_change_preserves_intent_without_installing_credential(prepared_root):
    probe,boot,w,cfg,release,commit=prepared_root
    def change(source,pin):subprocess.check_call(['git','--git-dir='+str(source),'update-ref','refs/heads/unexpected',pin])
    with pytest.raises(p.Stop,match='REFS_CHANGED'):
        p.provision(probe,boot,w,cfg,release,commit,apply=True,getter=lambda sha,path:(ROOT/path).read_bytes(),source_fetch=change)
    assert (w/(p.ATTEMPT+'-runtime-v2-intent.json')).exists()
    assert not (w/(p.ATTEMPT+'-runtime-v2-auth')).exists()


def test_review_mode_never_reads_token_or_runs_source_fetch(prepared_root,monkeypatch):
    probe,boot,w,cfg,release,commit=prepared_root
    original=probe.read_root
    def read(path,*a):
        assert path.name!='worker-github-token'
        return original(path,*a)
    monkeypatch.setattr(probe,'read_root',read)
    p.provision(probe,boot,w,cfg,release,commit)
    assert not (w/(p.ATTEMPT+'-runtime-v2-intent.json')).exists()


def test_actual_worker_git_owner_gate_and_credential_protocol_without_gh():
    if os.geteuid()!=0:pytest.skip('actual worker identity requires root collector CI')
    with tempfile.TemporaryDirectory(dir=ROOT) as folder:
        root=Path(folder);root.chmod(0o755);repo=root/'runner';repo.mkdir(mode=0o700)
        env={'PATH':'/usr/bin:/bin','HOME':'/nonexistent','GIT_CONFIG_NOSYSTEM':'1',
             'GIT_CONFIG_GLOBAL':'/dev/null','GIT_TERMINAL_PROMPT':'0','GIT_ASKPASS':'/bin/false'}
        def git(*args):return subprocess.check_output(['git','-C',str(repo),*args],env=env,stderr=subprocess.DEVNULL)
        git('init','-q');git('remote','add','origin','https://github.com/aliercankonus/signal-desk-prediction.git')
        git('-c','user.name=Offline','-c','user.email=offline@example.invalid','commit','--allow-empty','-qm','fixture')
        pin=git('rev-parse','HEAD').decode().strip()
        for path in [repo,*repo.rglob('*')]:os.chown(path,10000,10000)
        home=root/'home';home.mkdir(mode=0o700);os.chown(home,10000,10000)
        config=home/'gitconfig';config.write_text(c.GITCONFIG);config.chmod(0o600);os.chown(config,10000,10000)
        auth=root/'auth';auth.mkdir(mode=0o700);os.chown(auth,10000,10000)
        token=auth/'token';token.write_bytes(TOKEN);token.chmod(0o400);os.chown(token,10000,10000)
        driver=root/'driver.py'
        credential_source=str(ROOT/'ops/github_inbox/worker_credential.py')
        preflight_source=str(ROOT/'ops/github_inbox/worker_preflight.py')
        driver.write_text('import importlib.util,json,sys\n'
            'def load(path):\n s=importlib.util.spec_from_file_location("fixture",path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m\n'
            'c=load('+repr(credential_source)+');c.TOKEN=__import__("pathlib").Path('+repr(str(token))+')\n'
            'if sys.argv[1]=="owner":\n'
            ' p=load('+repr(preflight_source)+');p.PIN='+repr(pin)+';p.HELPER_MODULE='+repr(credential_source)+'\n'
            ' print(json.dumps(p.check(__import__("pathlib").Path('+repr(str(repo))+'),__import__("pathlib").Path('+repr(str(config))+'))))\n'
            'else: raise SystemExit(c.main())\n')
        driver.chmod(0o644)
        def uid():os.setgroups([]);os.setgid(10000);os.setuid(10000)
        def run(argv,data=None):return subprocess.run(argv,input=data,capture_output=True,env=env,timeout=15,preexec_fn=uid)
        owner=run([sys.executable,'-I','-B',str(driver),'owner'])
        assert owner.returncode==0 and json.loads(owner.stdout)=={'worker_owner_git':True,'credential_helper_configured':True}
        rejection=subprocess.run(['git','-C',str(repo),'rev-parse','HEAD'],env=env,capture_output=True,timeout=10)
        assert rejection.returncode and b'dubious ownership' in rejection.stderr
        config.write_text(c.GITCONFIG.replace('!/opt/hermes/.venv/bin/python -I -B /opt/worker-credential.py',
                                             '!'+sys.executable+' -I -B '+str(driver)))
        env['GIT_CONFIG_GLOBAL']=str(config)
        request=b'protocol=https\nhost=github.com\n\n'
        filled=run(['git','credential','fill'],request)
        assert filled.returncode==0 and b'password='+TOKEN in filled.stdout
        for action in ('approve','reject'):
            changed=run(['git','credential',action],request.rstrip(b'\n')+b'\nusername=x-access-token\npassword='+TOKEN+b'\n\n')
            assert changed.returncode==0 and token.read_bytes()==TOKEN
        token.chmod(0o600)
        refused=run([sys.executable,'-I','-B',str(driver),'get'],request)
        assert refused.returncode==1 and not refused.stdout and TOKEN not in refused.stderr
