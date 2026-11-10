import importlib.util
import json
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('runtime_probe', ROOT/'ops/bridge_one_shot/probe_worker_runtime.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
CID = 'a'*64


def result(**changes):
    r = dict(schema=1, test_versions=['3.14.9', '8.3.3'], worker_identity=True,
             git_available=True, gh_available=True, hermes_available=True,
             runner_head=True, runner_clean=True, versions_match=True, capability_pass=True)
    r.update(changes)
    return json.dumps(r).encode()


@pytest.fixture
def cfg():
    return dict(image='sha256:'+'b'*64, runner='/private/runner', venv='/private/venv')


class Engine:
    def __init__(self, cfg, *, timeout=False, mismatch=False, lost=False, blocked=False):
        self.cfg=cfg; self.timeout=timeout; self.mismatch=mismatch; self.lost=lost; self.blocked=blocked
        self.calls=[]; self.running=False; self.removed=False

    def __call__(self, a, timeout):
        self.calls.append((a, timeout))
        if a[:2]==['image', 'inspect']:
            return (self.cfg['image']+'\nnull\nPATH\nHOME\n\n').encode()
        if a[0]=='create':
            if self.lost: raise TimeoutError()
            return (CID+'\n').encode()
        if a[0]=='inspect':
            d={'.Id': CID, '.Image': self.cfg['image'], '.Config.User': '10000:10000',
               '.Config.Labels': {'signal-desk.capability':m.PROBE}, '.HostConfig.NetworkMode':'none',
               '.HostConfig.ReadonlyRootfs':True, '.HostConfig.CapDrop':['ALL'],
               '.HostConfig.SecurityOpt':['no-new-privileges'], '.HostConfig.Tmpfs':m.TMPFS,
               '.State.Running': self.running, '.State.ExitCode':0,
               '.HostConfig.Privileged':False, '.HostConfig.PidMode':'', '.HostConfig.IpcMode':'none',
               '.HostConfig.PidsLimit':64, '.HostConfig.Memory':536870912, '.HostConfig.NanoCpus':1000000000,
               '.HostConfig.RestartPolicy.Name':'no', '.Config.Entrypoint':[m.IMAGE_PYTHON],
               '.Config.Cmd':['-I','-B','-c',m.WORKER],
               '.Mounts':[dict(Type='bind',Source=s,Destination=t,RW=False,Propagation='rprivate') for s,t in
                          ((self.cfg['runner'],'/workspace/runner'),(self.cfg['venv'],str(Path(m.TEST_PYTHON).parent.parent)))]}
            if self.mismatch:d['.HostConfig.NetworkMode']='host'
            return ('\n'.join(json.dumps(d[k]) for k in m.FIELDS)+'\n').encode()
        if a[0]=='start':
            if self.timeout:self.running=True;raise subprocess.TimeoutExpired(a, timeout)
            return result(gh_available=False,capability_pass=False) if self.blocked else result()
        if a[0]=='kill':self.running=False;return b''
        if a[0]=='rm':assert not self.running;self.removed=True;return CID.encode()
        if a[0]=='ps':assert self.removed;return b''
        raise AssertionError(a)


def test_no_effect_default(tmp_path,cfg):
    def forbidden(*a):raise AssertionError('Docker called')
    m.probe(tmp_path,cfg,call=forbidden)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('blocked',[False,True])
def test_success_or_missing_tool_always_exact_cleanup(tmp_path,cfg,blocked,capsys):
    e=Engine(cfg,blocked=blocked);m.probe(tmp_path,cfg,apply=True,call=e)
    assert e.removed
    assert ('WORKER_RUNTIME: BLOCKED' if blocked else 'WORKER_RUNTIME: CAPABILITY_PASS') in capsys.readouterr().out
    receipt=json.loads((tmp_path/(m.PROBE+'-receipt.json')).read_text())
    assert receipt['cleanup_verified'] and not receipt['task_authority'] and not receipt['credentials_installed']
    assert all(a[-1]==CID for a,_ in e.calls if a[0] in ('kill','rm','start','inspect'))
    with pytest.raises(m.Stop,match='PRIOR_PROBE'):m.probe(tmp_path,cfg,apply=True,call=e)


def test_client_timeout_kills_only_verified_id_then_removes(tmp_path,cfg):
    e=Engine(cfg,timeout=True)
    with pytest.raises(m.Stop,match='INCOMPLETE'):m.probe(tmp_path,cfg,apply=True,call=e)
    assert e.removed and ['kill','--signal=KILL',CID] in [a for a,_ in e.calls]
    assert all(0<t<=75 for _,t in e.calls)


@pytest.mark.parametrize('option',['mismatch','lost'])
def test_uncertain_create_or_identity_never_started_or_deleted(tmp_path,cfg,option):
    e=Engine(cfg,**{option:True})
    with pytest.raises(m.Stop,match='INCOMPLETE'):m.probe(tmp_path,cfg,apply=True,call=e)
    assert not any(a[0] in ('start','kill','rm') for a,_ in e.calls)
    assert (tmp_path/(m.PROBE+'-intent.json')).exists()


def test_create_is_two_readonly_mounts_no_host_credentials(cfg):
    a=m.create_args(cfg)
    assert '--network=none' in a and '--read-only' in a and '--user=10000:10000' in a
    mounts=[a[i+1] for i,v in enumerate(a) if v=='--mount']
    assert len(mounts)==2 and all(',readonly,' in v for v in mounts)
    assert not any(s in ' '.join(mounts) for s in ('socket','token','auth','state','context','manager-key'))
    assert a[-1]==m.WORKER and '--pull=never' in a and '--cap-drop=ALL' in a
    assert 'safe.directory' not in m.WORKER


@pytest.mark.parametrize('change',[{'test_versions':['secret text','x']},{'schema':2},{'extra':'private'},
                                  {'runner_clean':False},{'test_versions':None}])
def test_worker_result_is_closed_and_consistent(change):
    with pytest.raises(m.Stop):m.validate_result(result(**change))


def test_worker_program_parses_and_has_no_auth_execution():
    compile(m.WORKER,'<worker>','exec')
    assert 'import hermes' not in m.WORKER and 'https://' not in m.WORKER
    assert "shutil.which(name)" in m.WORKER


def test_provenance_accepts_no_secret_reads_and_rejects_changed_spec(tmp_path,monkeypatch):
    cfg={k:'unused' for k in m.PLAN_KEYS}
    cfg.update(attempt=m.ATTEMPT,merge=m.ADAPTER_PIN,uid=10000,gid=10000,source='/source',
               test_python=m.TEST_PYTHON,python_version='3.14.9',pytest_version='8.3.3',
               runner=str(tmp_path/(m.ATTEMPT+'-runner')),venv=str(tmp_path/'venv'),
               image='sha256:'+'b'*64,start='unchanged historical start')
    raw=json.dumps(cfg).encode();bootstrap=b'public bootstrap fixture'
    monkeypatch.setattr(m,'PRESERVED',hashlib.sha256(bootstrap).hexdigest())
    records={'setup-manifest.json':dict(schema=1,workspace=str(tmp_path),purpose='public-setup-workspace-only',
                  runtime_authority=False,source='/source',venv_metadata={'path':cfg['venv']}),
             'private-inputs-receipt.json':dict(purpose='unused-cold-inputs-only',repo='aliercankonus/signal-desk-prediction',
                  activation=False,worker_credentials_installed=False,provider_authentication=False,task_authority=False,image=cfg['image']),
             m.ATTEMPT+'-staging-receipt.json':dict(schema=1,attempt=m.ATTEMPT,source_commit=m.STAGE_SOURCE,
                  original_spec_sha256=hashlib.sha256(raw).hexdigest(),preserved_bootstrap_sha256=m.PRESERVED,
                  completion_engine_sha256=m.ENGINE,runner_pin=m.RUNNER_PIN,adapter_pin=m.ADAPTER_PIN,
                  activation=False,worker_credentials_installed=False,original_spec_start=cfg['start']),
             m.ATTEMPT+'-operator-plan.json':{k:cfg[k] for k in m.PLAN_KEYS}}
    data={k:json.dumps(v).encode() for k,v in records.items()}
    data[m.ATTEMPT+'-bootstrap-spec.json']=raw;data[m.ATTEMPT+'-bootstrap.py']=bootstrap
    reads=[]
    def read(p,*a):reads.append(p.name);return data[p.name]
    monkeypatch.setattr(m,'read_root',read);monkeypatch.setattr(m,'root_dir',lambda p:None)
    monkeypatch.setattr(m.os,'geteuid',lambda:0)
    original=Path.lstat
    def metadata(p):
        if str(p) in (cfg['runner'],cfg['venv']):
            from types import SimpleNamespace
            return SimpleNamespace(st_mode=0o40700,st_uid=10000,st_gid=10000)
        return original(p)
    monkeypatch.setattr(Path,'lstat',metadata)
    assert m.inputs(str(tmp_path))[1]==cfg
    assert all('token' not in n and 'key' not in n for n in reads)
    data[m.ATTEMPT+'-bootstrap-spec.json']=raw+b' '
    with pytest.raises(m.Stop,match='PROVENANCE'):m.inputs(str(tmp_path))


def test_real_git_owner_namespace_without_safety_override():
    if os.geteuid()!=0:pytest.skip('actual root/worker transition requires root CI')
    with tempfile.TemporaryDirectory(prefix='probe-owner-',dir='/tmp') as folder:
        root=Path(folder);root.chmod(0o755);repo=root/'runner';repo.mkdir(mode=0o700)
        env={'PATH':'/usr/bin:/bin','HOME':'/nonexistent','GIT_CONFIG_GLOBAL':'/dev/null','GIT_CONFIG_NOSYSTEM':'1'}
        def git(*args,worker=False):
            def identity():os.setgroups([]);os.setgid(10000);os.setuid(10000)
            return subprocess.run(['git','--no-optional-locks','-C',str(repo),*args],env=env,
                  stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=10,preexec_fn=identity if worker else None)
        assert git('init','-q').returncode==0
        assert git('-c','user.name=Offline','-c','user.email=offline@example.invalid','commit','--allow-empty','-qm','fixture').returncode==0
        head=git('rev-parse','HEAD').stdout
        for p in [repo,*repo.rglob('*')]:os.chown(p,10000,10000)
        rejected=git('rev-parse','HEAD')
        assert rejected.returncode!=0 and b'dubious ownership' in rejected.stderr
        assert git('rev-parse','HEAD',worker=True).stdout==head
        assert git('status','--porcelain=v1','--untracked-files=all',worker=True).stdout==b''


@pytest.mark.parametrize('record',[b'sha256:'+b'b'*64+b'\n{"/unreviewed":{}}\nPATH\n\n',
                                  b'sha256:'+b'b'*64+b'\nnull\nSECRET_TOKEN\n\n'])
def test_unreviewed_image_names_or_volume_stop_before_intent(tmp_path,cfg,record):
    calls=[]
    def call(a,t):calls.append(a);return record
    with pytest.raises(m.Stop,match='IMAGE_METADATA'):m.probe(tmp_path,cfg,apply=True,call=call)
    assert len(calls)==1 and not list(tmp_path.iterdir())
