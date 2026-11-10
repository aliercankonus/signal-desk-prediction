import copy
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


def load(path,name):
    s=importlib.util.spec_from_file_location(name,ROOT/path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


w=load('ops/github_inbox/worker_preflight_v3.py','worker_v3')
m=load('ops/bridge_one_shot/authenticate_worker_clone_fix.py','corrected_auth')
OLD_ALLOWED={'core.repositoryformatversion','core.filemode','core.bare','core.logallrefupdates',
             'remote.origin.url','remote.origin.fetch','user.name','user.email'}


def git(*args):return subprocess.check_output(['git',*map(str,args)],stderr=subprocess.DEVNULL)


def clone_fixture(root):
    source=root/'source';source.mkdir()
    git('-C',source,'init','-q','-b','main')
    git('-C',source,'-c','user.name=Offline','-c','user.email=offline@example.invalid','commit','--allow-empty','-qm','fixture')
    runner=root/'runner';git('clone','--no-local','--no-checkout','-q',source,runner)
    git('-C',runner,'checkout','--detach','-q','HEAD')
    git('-C',runner,'remote','set-url','origin','https://github.com/aliercankonus/signal-desk-prediction.git')
    return runner


def test_real_normal_clone_tracking_rejected_by_old_gate_is_accepted_without_mutation(tmp_path):
    runner=clone_fixture(tmp_path)
    keys=git('-C',runner,'config','--local','--no-includes','--name-only','--list').decode().splitlines()
    assert {'branch.main.remote','branch.main.merge'}<=set(keys)
    assert not set(keys).issubset(OLD_ALLOWED)
    before={name:(runner/'.git'/name).read_bytes() for name in ('config','HEAD','index')}
    w.tracking_keys(keys,lambda parts:git('-C',runner,*parts))
    assert all((runner/'.git'/name).read_bytes()==data for name,data in before.items())


@pytest.mark.parametrize('key',['include.path','credential.helper','core.sshcommand','core.hookspath',
    'core.fsmonitor','filter.evil.clean','branch.main.pushremote','branch.main.rebase'])
def test_executable_and_credential_config_stays_closed(key):
    def forbidden(*a):raise AssertionError('must fail before value lookup')
    with pytest.raises(w.PreflightBlocked,match='LOCAL_CONFIG_KEY'):w.tracking_keys([key],forbidden)


@pytest.mark.parametrize('keys,remote,merge',[
    (['branch.main.remote'],b'origin\n',b'refs/heads/main\n'),
    (['branch.main.remote','branch.main.merge'],b'untrusted\n',b'refs/heads/main\n'),
    (['branch.main.remote','branch.main.merge'],b'origin\n',b'refs/heads/other\n'),
    (['branch.main.remote','branch.main.merge'],b'origin\norigin\n',b'refs/heads/main\n'),
    (['branch.main.remote','branch.main.remote','branch.main.merge'],b'origin\n',b'refs/heads/main\n')])
def test_incomplete_duplicate_or_noncanonical_tracking_fails(keys,remote,merge):
    with pytest.raises(w.PreflightBlocked):w.tracking_keys(keys,lambda a:remote if a[-1].endswith('.remote') else merge)


def prior():
    receipt=dict(schema=1,github_readonly_verified=False,device_cli_success=False,cleanup_verified=True,
        partial_startup=False,failure='AUTH_ERROR_CALLEDPROCESSERROR',enrollment=False,signing=False,
        dispatch=False,timer=False,model_entitlement='UNPROVEN',manager_exclusivity='UNPROVEN')
    phase=dict(version=1,attempt=m.ATTEMPT,phase='cleanup',status='pending',intent=None,
        unresolved_effect=None,owned=[],cleanup_verified=True,report_receipt=None)
    return receipt,phase


def test_only_exact_pre_auth_failure_with_verified_cleanup_is_admitted():
    r,p=prior();m.failure_records(r,p)
    for key,value in [('device_cli_success',True),('github_readonly_verified',True),('cleanup_verified',False),
                       ('partial_startup',True),('dispatch',True),('failure','unknown')]:
        bad=dict(r);bad[key]=value
        with pytest.raises(m.Stop):m.failure_records(bad,p)
    for key,value in [('owned',[{'ident':'unknown'}]),('unresolved_effect','cleanup'),('intent','login'),
                       ('cleanup_verified',False),('report_receipt','unexpected')]:
        bad=dict(p);bad[key]=value
        with pytest.raises(m.Stop):m.failure_records(r,bad)


def test_embedded_readonly_correction_is_exact_repo_source():
    assert m.WORKER_PREFLIGHT_V3==(ROOT/'ops/github_inbox/worker_preflight_v3.py').read_bytes()
    assert 'safe.directory' not in m.WORKER_PREFLIGHT_V3.decode()
    assert w.PIN==m.RUNNER=='e84021a786004456a12de9e25eae50d191da6cf1'


class Journal:
    def __init__(self,directory):self.directory=directory;self.state={}
    def create(self):self.directory.mkdir(mode=0o700)
    def record(self,phase,**kw):self.state.update(phase=phase,**kw)


def minimal_plan(root):
    return SimpleNamespace(journal_parent=root,attempt=m.ATTEMPT,bundle=Path('/frozen'),runner=Path('/runner'),
        state=Path('/state'),auth=Path('/auth'),context=Path('/context'),home=Path('/home'),venv=Path('/venv'),inbox=Path('/inbox'))


def test_overlay_replaces_only_preflight_source_and_is_readonly(tmp_path):
    p=minimal_plan(tmp_path)
    services={}
    for service in ('inbox-worker','connect-proxy'):
        entries=[]
        for (target,source),rw in m.mounts(p,service).items():
            if target=='/opt/worker-preflight.py':source=str(p.bundle/'worker_preflight.py')
            entries.append(dict(type='bind',target=target,source=source,read_only=not rw))
        services[service]=dict(volumes=entries,environment={})
    r=m.auth_config(dict(services=services),p)
    actual=next(x for x in r['services']['inbox-worker']['volumes'] if x['target']=='/opt/worker-preflight.py')
    assert actual['source']==str(m.correction_file(p)) and actual['read_only']
    assert '/frozen/' not in actual['source']


def test_sanitized_owner_failure_stage_does_not_echo_child_output(tmp_path,monkeypatch):
    p=minimal_plan(tmp_path);j=Journal(tmp_path/m.CORRECTED_JOURNAL)
    monkeypatch.setattr(m,'preflight',lambda *a:None);monkeypatch.setattr(m,'configure',lambda *a:None)
    monkeypatch.setattr(m,'auth_config',lambda r,p:r)
    class Ops:
        plan=p
        def _compose(self,*a):return '{}'
        def start_isolation(self):return tuple(SimpleNamespace() for _ in range(5))
        def _worker(self,*a,**kw):
            raise subprocess.CalledProcessError(1,'fixed child',output=b'WORKER_PREFLIGHT: BLOCKED CODE=LOCAL_CONFIG_KEY\n',stderr=b'PRIVATE_DATA_MUST_NOT_APPEAR')
        def inspect_owned(self,r):return True
        def cleanup(self,r):return r
        def cleanup_readback(self,r):return True
        def github_reads(self):raise AssertionError('no GitHub request after failed owner check')
    result=m.run(j,Ops(),SimpleNamespace(Owned=SimpleNamespace),deadline=2000,clock=lambda:1000,
                 authenticate=lambda *a,**kw:pytest.fail('no provider request'))
    assert result['failure_phase']=='OWNER_PREFLIGHT' and result['worker_preflight_code']=='LOCAL_CONFIG_KEY'
    assert result['child_exit_code']==1 and result['cleanup_verified']
    assert b'PRIVATE_DATA' not in (j.directory/'auth-only-receipt.json').read_bytes()
    assert m.correction_file(p).stat().st_mode&0o777==0o444


def test_actual_root_prior_journal_is_preserved_and_second_entry_cannot_be_repeated():
    if os.geteuid()!=0:pytest.skip('actual root journal metadata requires root CI')
    with tempfile.TemporaryDirectory(dir=Path.home()) as d:
        parent=Path(d);parent.chmod(0o700);p=SimpleNamespace(journal_parent=parent)
        old=parent/(m.ATTEMPT+'-auth-only-01');old.mkdir(mode=0o700);receipt,phase=prior()
        for name,data in [('auth-only-receipt.json',receipt),('phase.json',phase),('compose.auth-only.json',{})]:
            f=old/name;f.write_text(json.dumps(data));f.chmod(0o600)
        before={f.name:f.read_bytes() for f in old.iterdir()};m.prior_failure(p)
        assert all((old/name).read_bytes()==data for name,data in before.items())
        (parent/m.CORRECTED_JOURNAL).mkdir(mode=0o700)
        with pytest.raises(m.Stop,match='JOURNAL_HISTORY'):m.prior_failure(p)


def test_actual_owner_with_normal_clone_passes_new_gate_without_git_safety_override():
    if os.geteuid()!=0:pytest.skip('actual cross-UID Git integration requires root CI')
    with tempfile.TemporaryDirectory(dir=ROOT) as d:
        root=Path(d);root.chmod(0o755);runner=clone_fixture(root);pin=git('-C',runner,'rev-parse','HEAD').decode().strip()
        for path in [runner,*runner.rglob('*')]:os.chown(path,10000,10000)
        home=root/'home';home.mkdir(mode=0o700);os.chown(home,10000,10000)
        helper=load('ops/github_inbox/worker_credential.py','fixture_credential')
        config=home/'gitconfig';config.write_text(helper.GITCONFIG);config.chmod(0o600);os.chown(config,10000,10000)
        script=root/'driver.py'
        script.write_text('import importlib.util,json\nfrom pathlib import Path\n'
            's=importlib.util.spec_from_file_location("worker",'+repr(str(ROOT/'ops/github_inbox/worker_preflight_v3.py'))+');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)\n'
            'm.PIN='+repr(pin)+';m.HELPER_MODULE='+repr(str(ROOT/'ops/github_inbox/worker_credential.py'))+'\n'
            'print(json.dumps(m.check(Path('+repr(str(runner))+'),Path('+repr(str(config))+'))))\n')
        script.chmod(0o644)
        def worker():os.setgroups([]);os.setgid(10000);os.setuid(10000)
        result=subprocess.run([sys.executable,'-I','-B',str(script)],capture_output=True,timeout=15,preexec_fn=worker)
        assert result.returncode==0 and json.loads(result.stdout)=={'worker_owner_git':True,'credential_helper_configured':True}
        rejected=subprocess.run(['git','-C',str(runner),'rev-parse','HEAD'],capture_output=True,timeout=10,
            env={'PATH':'/usr/bin:/bin','HOME':'/nonexistent','GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':'/dev/null'})
        assert rejected.returncode and b'dubious ownership' in rejected.stderr
