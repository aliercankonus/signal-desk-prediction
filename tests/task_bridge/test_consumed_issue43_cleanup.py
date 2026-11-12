import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('consumed_cleanup',ROOT/'ops/bridge_one_shot/cleanup_consumed_issue43.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
W='a'*64;P='b'*64;N='c'*64;U='d'*64;O='e'*64
JUMPS='-A INPUT -s 172.30.50.2/32 -i br-sd-once -j SD_ONCE_IN\n-A DOCKER-USER -s 172.30.50.2/32 -i br-sd-once -j SD_ONCE_FWD\n'


def rows():return [dict(kind=k,ident=i,proof=m.ATTEMPT) for k,i in [('worker',W),('proxy',P),('network',N),('network',U),('firewall','SD_ONCE_IN'),('enrollment','123')]]


def test_only_complete_root_owned_identity_set_is_accepted():
    assert m.owned(rows(),m.ATTEMPT)['worker']==[W]
    for bad in (rows()[:-1],rows()+[rows()[0]],[dict(x,proof='other') for x in rows()],
        [dict(x,ident='bad') if x['kind']=='worker' else x for x in rows()],
        [dict(x,kind='scheduler') if x['kind']=='proxy' else x for x in rows()]):
        with pytest.raises(m.Stop):m.owned(bad,m.ATTEMPT)


@pytest.mark.parametrize('extra',['-A OUTPUT -j SD_ONCE_IN\n','-A INPUT -s 10.1.1.1/32 -i br-sd-once -j SD_ONCE_IN\n',
    '-A INPUT -s 172.30.50.2/32 -i another-bridge -j SD_ONCE_IN\n',JUMPS])
def test_other_firewall_references_are_a_refusal_before_rollback(extra):
    m.firewall_references(JUMPS)
    with pytest.raises(m.Stop):m.firewall_references(JUMPS+extra)


class Ops:
    worker_id=W;proxy_id=P;network_ids={'worker_isolated':N,'proxy_uplink':U}
    plan=SimpleNamespace(bundle=Path('/root/frozen'))
    def __init__(self,fail_stop=False,change_baseline=False):
        self.containers={W,P,O};self.networks={N,U,O};self.running={W,P};self.rules=True
        self.events=[];self.fail_stop=fail_stop;self.change_baseline=change_baseline
    def _docker(self,*args,**kw):
        self.events.append(('docker',args))
        if args[:2]==('ps','-aq'):return '\n'.join(sorted(self.containers))+'\n'
        if args[:3]==('network','ls','-q'):return '\n'.join(sorted(self.networks))+'\n'
        if args[:1]==('stop',):
            assert args[1:3]==('--time','5') and args[3] in (W,P)
            if self.fail_stop:raise RuntimeError('fixed simulated stop ambiguity')
            self.running.remove(args[3]);return args[3]
        if args[:1]==('rm',):
            assert args[1] in (W,P) and args[1] not in self.running
            self.containers.remove(args[1]);return args[1]
        if args[:2]==('network','rm'):
            assert not ({W,P}&self.containers) and args[2] in (N,U)
            self.networks.remove(args[2])
            if self.change_baseline:self.networks.add('f'*64)
            return args[2]
        raise AssertionError('unapproved command: '+repr(args))
    def _call(self,args,**kw):
        self.events.append(('call',args))
        if args==['iptables','-S']:return JUMPS if self.rules else '-P INPUT ACCEPT\n'
        assert args[:2]==['bash',self.plan.bundle/'worker_firewall.sh']
        if args[-1]=='status':assert self.rules;return 'PASS'
        assert args[-1]=='rollback' and W not in self.containers
        assert kw['env']=={'AUTODEV_FIREWALL_APPROVED':'yes-for-reviewed-network'}
        self.rules=False;return ''
    def _network(self,role):
        assert not ({W,P}&self.containers);self.events.append(('empty-network',role))


def inspection(ops,auth,ident,service,running):
    assert (ident,service) in ((W,'inbox-worker'),(P,'connect-proxy'))
    assert ident in ops.containers and (running is None or (ident in ops.running)==running)
    ops.events.append(('inspect',ident,running))
    return ident in ops.running


def test_stop_verify_remove_order_and_only_owned_cleanup(monkeypatch):
    monkeypatch.setattr(m,'exact_container',inspection);ops=Ops();writes=[]
    m.cleanup(ops,None,lambda name,data:writes.append(name))
    assert ops.containers==ops.networks=={O} and not ops.rules
    assert writes.index('stop-worker-intent')<writes.index('stop-worker-verified')<writes.index('remove-worker-intent')
    assert writes.index('remove-worker-verified')<writes.index('firewall-rollback-intent')<writes.index('stop-proxy-intent')
    assert writes[-1]=='runtime-cleanup-verified'
    assert all('exec' not in event[1] for event in ops.events if event[0]=='docker')


def test_partial_stop_preserves_intent_and_does_not_guess_next_cleanup(monkeypatch):
    monkeypatch.setattr(m,'exact_container',inspection);ops=Ops(fail_stop=True);writes=[]
    with pytest.raises(RuntimeError):m.cleanup(ops,None,lambda name,data:writes.append(name))
    assert writes==['baseline','stop-worker-intent'] and ops.containers=={W,P,O} and ops.rules
    assert not any(e[0]=='docker' and e[1][0]=='rm' for e in ops.events)


def test_unrelated_resource_concurrency_is_not_reported_as_verified_cleanup(monkeypatch):
    monkeypatch.setattr(m,'exact_container',inspection);ops=Ops(change_baseline=True);writes=[]
    with pytest.raises(m.Stop,match='UNRELATED_RESOURCE_BASELINE_CHANGED'):
        m.cleanup(ops,None,lambda name,data:writes.append(name))
    assert 'runtime-cleanup-verified' not in writes


def test_real_entry_directory_refuses_repeat_after_an_ambiguous_effect(tmp_path,monkeypatch,capsys):
    import importlib.util
    ds=importlib.util.spec_from_file_location('diag_for_cleanup',ROOT/'ops/bridge_one_shot/inspect_blocked_issue43.py')
    diag=importlib.util.module_from_spec(ds);ds.loader.exec_module(diag)
    ops=Ops(fail_stop=True);fake_diag=SimpleNamespace(fresh_json=diag.fresh_json,QUEUE=diag.QUEUE,RUN=diag.RUN)
    monkeypatch.setattr(m,'public',lambda name:fake_diag if name=='diag' else SimpleNamespace())
    monkeypatch.setattr(m,'load',lambda *a:(tmp_path,ops,tmp_path/'phase',b'history',tmp_path/'inbox',b'claim'))
    monkeypatch.setattr(m,'exact_container',inspection)
    monkeypatch.setattr(sys,'argv',['cleanup','--workspace',str(tmp_path),'--cleanup'])
    assert m.main()==1
    before=list(ops.events);files={p.name:p.read_bytes() for p in (tmp_path/(m.ATTEMPT+'-exact-cleanup-01')).iterdir()}
    assert m.main()==1 and ops.events==before
    assert all((tmp_path/(m.ATTEMPT+'-exact-cleanup-01')/name).read_bytes()==data for name,data in files.items())
    assert 'STOP' in capsys.readouterr().out


@pytest.mark.parametrize('bad',[None,'network-peer','network-label','network-geometry','container','claim','owned'])
def test_load_verifies_the_complete_recorded_identity_before_any_effect(tmp_path,bad,monkeypatch):
    import hashlib
    inbox=tmp_path/'state'/'github-inbox';inbox.mkdir(parents=True)
    plan=SimpleNamespace(bundle=tmp_path/'bundle',journal_parent=tmp_path/'journals',state=tmp_path/'state',uid=10000)
    phase_rows=rows();phase_rows[-1]['ident']=str(inbox.stat().st_ino)
    if bad=='owned':phase_rows[0]['proof']='foreign'
    phase_bytes=json.dumps(dict(owned=phase_rows,unresolved_effect='one_bridge_claim',intent=None,cleanup_verified=False)).encode()
    state_bytes=json.dumps(dict(claim=dict(status='running' if bad=='claim' else 'blocked',queue_id='queue',grant_id=6777657372,
        instruction_id=6775497757,publication_intent=None))).encode()
    diagnostic=json.dumps(dict(queue=dict(invocations=1,status='blocked'),bridge=dict(status='blocked',failure=dict(category='child_nonzero',
        duration_ms=19067,exit_code=1,signal=None,stage='child_invocation',stop_reason='exit_nonzero'))))
    blob_map={tmp_path/(m.ATTEMPT+'-issue43-diagnostic-report-receipt'):json.dumps(dict(id=6778310463,verified=True,
        body_sha256=hashlib.sha256(diagnostic.encode()).hexdigest())).encode(),plan.bundle/'fixture.py':b'reviewed',
        plan.journal_parent/(m.ATTEMPT+'-issue43-once')/'phase.json':phase_bytes}
    calls=[]
    class ReadOnlyOps:
        def __init__(self,*a,**kw):self.plan=plan;self.network_ids={}
        def _docker(self,*args,**kw):
            calls.append(args);assert args[:2]==('network','inspect')
            role='worker_isolated' if args[2]==N else 'proxy_uplink'
            labels={'com.docker.compose.network':role,'org.signal-desk.issue41.attempt':m.ATTEMPT}
            if bad=='network-label':labels['org.signal-desk.issue41.attempt']='other'
            peers={W:{'IPv4Address':'172.30.50.2/28'},P:{'IPv4Address':'172.30.50.3/28'}} if role=='worker_isolated' else {P:{'IPv4Address':'172.30.51.2/28'}}
            if bad=='network-peer':peers[O]={}
            return json.dumps([dict(Id=args[2],Labels=labels,Containers=peers)])
        def _container(self,ident,service,*,running):
            calls.append(('metadata',ident,service,running))
            if bad=='container':raise m.Stop('TEST_CONFINEMENT_REFUSAL')
            assert (ident,service,running) in ((W,'inbox-worker',None),(P,'connect-proxy',None))
            return True
        def _call(self,args,**kw):
            calls.append(args)
            assert args in (['bash',plan.bundle/'worker_firewall.sh','status'],['iptables','-S'])
            return JUMPS if args[0]=='iptables' else 'PASS'
    host=SimpleNamespace(load_plan=lambda p:plan,trusted_worker_mount=lambda *a:None,
        worker_private_bytes=lambda *a:state_bytes,HostOperations=ReadOnlyOps,CommandRunner=lambda **kw:None)
    def validate_network(row,role,proxy_id):
        assert set(row['Containers'])=={P} and proxy_id==P
        if bad=='network-geometry':raise m.Stop('TEST_NETWORK_GEOMETRY_REFUSAL')
        return row['Id']
    auth=SimpleNamespace(blob=lambda p,**kw:blob_map[p],root_dir=lambda p:None,RELEASE={'fixture.py':hashlib.sha256(b'reviewed').hexdigest()},
        protected_module=lambda name,p:host if name=='_protected_cleanup_host' else SimpleNamespace(validate_attempt_network=validate_network),
        mounts=lambda *a:{},configure=lambda *a:None)
    task=SimpleNamespace(TASK_JOURNAL=m.ATTEMPT+'-issue43-once',task_mounts=lambda *a:{})
    diag=SimpleNamespace(inspect=lambda *a:(tmp_path,{'bundle':str(plan.bundle)},diagnostic),QUEUE='queue')
    monkeypatch.setattr(m,'exact_container',lambda ops,auth,ident,service,running:ops._container(ident,service,running=running))
    if bad:
        with pytest.raises(m.Stop):m.load(str(tmp_path),auth,task,diag)
    else:
        w,ops,p,pbytes,s,sbytes=m.load(str(tmp_path),auth,task,diag)
        assert w==tmp_path and pbytes==phase_bytes and sbytes==state_bytes
        assert ops.worker_id==W and ops.proxy_id==P and ops.network_ids=={'worker_isolated':N,'proxy_uplink':U}
    assert all('stop' not in item and 'rm' not in item and 'rollback' not in item and 'exec' not in item for item in calls)


@pytest.mark.parametrize('stopped',[{W},{P},{W,P}])
def test_known_stopped_containers_are_removed_without_start_or_second_stop(monkeypatch,stopped):
    monkeypatch.setattr(m,'exact_container',inspection);ops=Ops();ops.running-=stopped;writes=[]
    m.cleanup(ops,None,lambda name,data:writes.append(name))
    stops=[event[1][-1] for event in ops.events if event[0]=='docker' and event[1][0]=='stop']
    assert set(stops)=={W,P}-stopped
    assert ops.containers==ops.networks=={O} and writes[-1]=='runtime-cleanup-verified'


def test_live_network_accepts_only_owned_running_or_stopped_peers():
    calls=[]
    validator=SimpleNamespace(validate_attempt_network=lambda row,role,proxy_id:(calls.append((row,proxy_id)) or row['Id']))
    row=dict(Id=N,Containers={P:{'IPv4Address':'172.30.50.3/28'}})
    m.live_network(row,'worker_isolated',W,P,{W:False,P:True},validator)
    assert calls[-1][1]==P
    m.live_network(dict(Id=N,Containers={}), 'worker_isolated',W,P,{W:False,P:False},validator)
    assert calls[-1][1] is None
    with pytest.raises(m.Stop):m.live_network(row,'worker_isolated',W,P,{W:True,P:True},validator)
    with pytest.raises(m.Stop):m.live_network(dict(Id=N,Containers={O:{}}),'worker_isolated',W,P,{W:False,P:False},validator)
    with pytest.raises(m.Stop):m.live_network(dict(Id=N,Containers={P:{'IPv4Address':'10.1.1.1/24'}}),'worker_isolated',W,P,{W:False,P:True},validator)
