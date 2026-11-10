import copy
import dataclasses
import importlib.util
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace

import pytest

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('auth_only',ROOT/'ops/bridge_one_shot/authenticate_worker_once.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def plan():
    from test_operator_host import plan as original
    return original()


def record(service='inbox-worker'):
    p=plan();proxy=service=='connect-proxy'
    nets={'signal-desk-bridge-once_worker_isolated':{}}
    if proxy:nets['signal-desk-bridge-once_proxy_uplink']={}
    return {'.Id':'a'*64,'.Image':p.image,'.Config.Labels':{'org.signal-desk.issue41.attempt':p.attempt,
        'com.docker.compose.project':'signal-desk-bridge-once','com.docker.compose.service':service},
        '.Config.User':'65534:65534' if proxy else '10000:10000','.State.Running':True,
        '.HostConfig.ReadonlyRootfs':True,'.HostConfig.Privileged':False,'.HostConfig.CapDrop':['ALL'],
        '.HostConfig.SecurityOpt':['no-new-privileges:true'],'.HostConfig.PidMode':'','.HostConfig.IpcMode':'private',
        '.HostConfig.NetworkMode':'signal-desk-bridge-once_worker_isolated',
        '.HostConfig.PidsLimit':32 if proxy else 128,'.HostConfig.Memory':134217728 if proxy else 1610612736,
        '.HostConfig.NanoCpus':250000000 if proxy else 1000000000,'.HostConfig.RestartPolicy.Name':'no',
        '.HostConfig.Tmpfs':m.tmpfs(service),'.HostConfig.CapAdd':None,'.HostConfig.Devices':[],'.HostConfig.DeviceRequests':None,
        '.HostConfig.UsernsMode':'','.HostConfig.CgroupnsMode':'private',
        '.Config.Entrypoint':['/opt/hermes/.venv/bin/python'],
        '.Config.Cmd':['-B','/opt/connect-proxy.py'] if proxy else ['-I','-B','-c','import time; time.sleep(7200)'],
        '.Mounts':[dict(Type='bind',Destination=t,Source=s,RW=rw,Propagation='rprivate')
        for (t,s),rw in m.mounts(p,service).items()],'.NetworkSettings.Networks':nets,'.NetworkSettings.Ports':{}}


@pytest.mark.parametrize('service',['connect-proxy','inbox-worker'])
def test_actual_confinement_contract(service):
    d=record(service)
    assert m.confined(d,'a'*64,service,plan(),True)['Id']=='a'*64
    assert '.Config.Env' not in m.FORMAT


@pytest.mark.parametrize('key,value',[
    ('.Config.User','0:0'),('.HostConfig.Privileged',True),('.HostConfig.ReadonlyRootfs',False),
    ('.HostConfig.PidMode','host'),('.HostConfig.IpcMode','host'),('.HostConfig.NetworkMode','container:other'),
    ('.HostConfig.CapDrop',[]),('.HostConfig.SecurityOpt',[]),('.NetworkSettings.Ports',{'80/tcp':[{}]}),
    ('.NetworkSettings.Networks',{'host':{}}),('.HostConfig.RestartPolicy.Name','always'),
    ('.HostConfig.CapAdd',['SYS_ADMIN']),('.HostConfig.Devices',[{}]),('.HostConfig.CgroupnsMode','host'),
    ('.Config.Cmd',['hermes','chat','unapproved'])])
def test_wrong_privilege_namespace_or_port_stops_before_auth(key,value):
    d=record();d[key]=value
    with pytest.raises(m.Stop):m.confined(d,'a'*64,'inbox-worker',plan(),True)


def test_root_or_writable_extra_mount_is_rejected():
    for extra in (dict(Type='bind',Source='/',Destination='/host',RW=False,Propagation='rprivate'),
                  dict(Type='volume',Source='/volume',Destination='/opt/data',RW=True)):
        d=record();d['.Mounts'].append(extra)
        with pytest.raises(m.Stop):m.confined(d,'a'*64,'inbox-worker',plan(),True)
    d=record();d['.Mounts'][0]['RW']=True
    with pytest.raises(m.Stop):m.confined(d,'a'*64,'inbox-worker',plan(),True)


def rendered():
    p=plan()
    return {'services':{s:{'volumes':[dict(type='bind',source=src,target=target,read_only=False)
            for target,src in m.mounts(p,s)],'environment':{}} for s in ('inbox-worker','connect-proxy')}}


def test_auth_compose_keeps_only_home_writable_and_masks_old_homes():
    r=m.auth_config(rendered(),plan())
    w=r['services']['inbox-worker']
    assert [v['target'] for v in w['volumes'] if not v['read_only']]==['/worker-home']
    assert set(x.split(':')[0] for x in w['tmpfs'])==set(m.TMPFS)
    bad=rendered();bad['services']['inbox-worker']['volumes'][0]['source']='/different'
    with pytest.raises(m.Stop):m.auth_config(bad,plan())


class Journal:
    def __init__(self,path):self.directory=path;self.state={'intent':None};self.calls=[]
    def create(self):self.calls.append('create')
    def record(self,phase,**kw):self.calls.append((phase,kw));self.state.update(kw)


class Ops:
    def __init__(self):
        self.plan=plan();self.calls=[];self.fail_start=False;self.cleanup_ok=True
        self.enrollment_inode=None;self.deadline=None
    def _compose(self,*args):return json.dumps(rendered())
    def start_isolation(self):
        self.calls.append('start')
        if self.fail_start:raise TimeoutError()
        return tuple(SimpleNamespace() for _ in range(5))
    def _worker(self,*args,**kw):
        self.calls.append('owner');return json.dumps(dict(worker_owner_git=True,credential_helper_configured=True))
    def github_reads(self):self.calls.append('github')
    def inspect_owned(self,r):self.calls.append('inspect');return self.cleanup_ok
    def cleanup(self,r):self.calls.append('cleanup');return r
    def cleanup_readback(self,r):self.calls.append('readback');return self.cleanup_ok
    def __getattr__(self,name):
        if name in ('login','enroll_disabled','enable_inbox','one_bridge_claim','reconcile','report','_inbox'):
            raise AssertionError('forbidden method '+name)
        raise AttributeError(name)


def setup_flow(monkeypatch):
    monkeypatch.setattr(m,'preflight',lambda *a:None)
    monkeypatch.setattr(m,'configure',lambda *a:None)


def test_auth_only_sequence_and_cleanup_never_reach_task_methods(tmp_path,monkeypatch):
    setup_flow(monkeypatch);ops=Ops();j=Journal(tmp_path)
    def auth(ops,**kw):ops.calls.append('device')
    result=m.run(j,ops,SimpleNamespace(Owned=SimpleNamespace),deadline=2000,clock=lambda:1000,authenticate=auth)
    assert ops.calls==['start','owner','github','device','inspect','cleanup','readback']
    assert result['cleanup_verified'] and result['device_cli_success'] and result['github_readonly_verified']
    assert not any(result[k] for k in ('enrollment','signing','dispatch','timer'))
    assert result['manager_exclusivity']==result['model_entitlement']=='UNPROVEN'


def test_provider_timeout_cleans_actual_container_not_just_client(tmp_path,monkeypatch):
    setup_flow(monkeypatch);ops=Ops()
    def timeout(*a,**kw):raise TimeoutError()
    r=m.run(Journal(tmp_path),ops,SimpleNamespace(Owned=SimpleNamespace),deadline=2000,clock=lambda:1000,authenticate=timeout)
    assert not r['device_cli_success'] and r['cleanup_verified'] and 'cleanup' in ops.calls


def test_partial_startup_preserves_unknown_resources_and_intent(tmp_path,monkeypatch):
    setup_flow(monkeypatch);ops=Ops();ops.fail_start=True;j=Journal(tmp_path)
    r=m.run(j,ops,SimpleNamespace(Owned=SimpleNamespace),deadline=2000,clock=lambda:1000)
    assert r['partial_startup'] and not r['cleanup_verified'] and ops.calls==['start']
    assert j.state['unresolved']=='start_isolation'


def test_failed_cleanup_never_claims_success(tmp_path,monkeypatch):
    setup_flow(monkeypatch);ops=Ops();ops.cleanup_ok=False
    r=m.run(Journal(tmp_path),ops,SimpleNamespace(Owned=SimpleNamespace),deadline=2000,clock=lambda:1000,authenticate=lambda *a,**kw:None)
    assert not r['cleanup_verified'] and r['failure']=='CLEANUP_UNVERIFIED'


def test_readonly_github_failure_prevents_provider_request(tmp_path,monkeypatch):
    setup_flow(monkeypatch);ops=Ops()
    def fail():raise ValueError()
    ops.github_reads=fail
    def forbidden(*a,**kw):raise AssertionError('provider must not start')
    r=m.run(Journal(tmp_path),ops,SimpleNamespace(Owned=SimpleNamespace),deadline=2000,clock=lambda:1000,authenticate=forbidden)
    assert not r['github_readonly_verified'] and not r['device_cli_success'] and r['cleanup_verified']


def test_frozen_bundle_hashes_are_exact():
    import hashlib
    release=json.loads((ROOT/'ops/bridge_one_shot/runtime_v2_release.json').read_text())
    assert m.RELEASE==release['files']
    assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==digest for p,digest in m.RELEASE.items())


@pytest.mark.parametrize('change',[None,'peer','environment'])
def test_actual_peer_and_environment_names_are_checked_without_values(change):
    p=plan();worker='a'*64;proxy='b'*64;network='c'*64
    class Platform:
        plan=p;proxy_id=proxy;network_ids={'worker_isolated':network}
        def _docker(self,*args,**kw):
            if args[:2]==('network','inspect'):
                peers={worker:{'IPv4Address':'172.30.50.2/28'},proxy:{'IPv4Address':'172.30.50.3/28'}}
                if change=='peer':peers['d'*64]={}
                return json.dumps([{'Id':network,'Containers':peers}])
            if args[4]==m.FORMAT:
                d=record();return '\n'.join(json.dumps(d[k]) for k in m.SELECT)+'\n'
            assert 'println (index (split' in args[4]
            return 'PATH\nHOME\n'+('LD_PRELOAD\n' if change=='environment' else '')+'\n'
    platform=Platform();m.configure(platform,Path('/protected/config'))
    if change:
        with pytest.raises(m.Stop):platform._container(worker,'inbox-worker',running=True)
    else:assert platform._container(worker,'inbox-worker',running=True)['Id']==worker


def test_device_deadline_kills_client_and_restores_terminal(monkeypatch):
    events=[]
    ops=SimpleNamespace(worker_id='a'*64,_container=lambda *a,**kw:None,
        _worker=lambda *a,**kw:'--type --timeout --no-browser')
    class Child:
        pid=42;stopped=False
        def wait(self,timeout):
            if not self.stopped:
                assert timeout==123
                raise m.subprocess.TimeoutExpired('docker',timeout)
            return 0
        def poll(self):return 0 if self.stopped else None
    child=Child()
    def kill(pid,sig):events.append(('kill',pid,sig));child.stopped=True
    monkeypatch.setattr(m.subprocess,'Popen',lambda *a,**kw:child)
    monkeypatch.setattr(m.os,'killpg',kill)
    monkeypatch.setattr(m.termios,'tcgetattr',lambda fd:['saved'])
    monkeypatch.setattr(m.termios,'tcsetattr',lambda *a:events.append(('restore',a)))
    with pytest.raises(m.subprocess.TimeoutExpired):m.device(ops,deadline=1123,clock=lambda:1000)
    assert events[0][0]=='kill' and events[-1][0]=='restore'


def test_actual_protected_blob_refuses_symlink_overwrite_or_owner_change():
    if os.geteuid()!=0:pytest.skip('real root metadata requires root CI')
    with tempfile.TemporaryDirectory(dir=Path.home()) as folder:
        root=Path(folder);root.chmod(0o700);m.root_dir(root)
        f=root/'public';f.write_bytes(b'public');f.chmod(0o600)
        assert m.blob(f)==b'public'
        link=root/'link';link.symlink_to(f)
        with pytest.raises(m.Stop):m.blob(link)
        os.chown(f,10000,10000)
        with pytest.raises(m.Stop):m.blob(f)


def test_proposed_loader_has_verified_digest_syntax_and_live_tty_reconnection():
    import hashlib, subprocess
    text=(ROOT/'ops/bridge_one_shot/AUTHENTICATE_WORKER_ONCE.md').read_text()
    block=text.split('```bash\n')[1].split('```')[0]
    assert subprocess.run(['bash','-n'],input=block.encode(),capture_output=True).returncode==0
    code=block.split("<<'PYCODE'\n")[1].rsplit('\nPYCODE',1)[0]
    compile(code,'<proposed-auth-loader>','exec')
    assert "digest = '"+hashlib.sha256((ROOT/'ops/bridge_one_shot/authenticate_worker_once.py').read_bytes()).hexdigest()+"'" in code
    assert code.index('hashlib.sha256')<code.index("os.open('/dev/tty'")<code.index("namespace['main']()")
    assert 'os.dup2(tty, 0)' in code
