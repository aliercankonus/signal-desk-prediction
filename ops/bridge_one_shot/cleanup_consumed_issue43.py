"""Operator-only exact runtime cleanup for the consumed #43 attempt.

No task continuation, model call, login, key/sign operation, enqueue or timer.
All original journals/bind-mounted files survive. A fresh cleanup directory is
one-use: any partial effect refuses automatic replay.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import signal
import sys
import time
import types
import urllib.request

ATTEMPT='issue41-cold-20261110-01'
PUBLIC={
 'auth':('5d1a005ae3a3a5816fd94ae085d6d81797e4cdf6','authenticate_worker_clone_fix.py','405e3a9ce73cf22403ea9d75a976df920cc99c1517b057749caa9681434f4b84'),
 'task':('09aa854e8e1751f62286c0c1fc686a634d299729','run_authorized_issue43.py','374d1799d2b63488fc77811e87d659d574fb8660d6735c37d7c0855f63591ee9'),
 'diag':('1712083e1cc5d576111695e0c26381fdb32c4245','inspect_blocked_issue43.py','505e0db2165499a26925348925523e53c7284346c8f87b608cc1344d8ce2b50b')}
class Stop(Exception):pass


def public(name):
    commit,file,digest=PUBLIC[name]
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*a,**kw):raise Stop('PUBLIC_REDIRECT')
    if signal.getitimer(signal.ITIMER_REAL)[0]:raise Stop('EXISTING_TIMER')
    previous=signal.getsignal(signal.SIGALRM)
    def timeout(*_):raise TimeoutError()
    signal.signal(signal.SIGALRM,timeout);signal.alarm(20)
    try:
        url='https://raw.githubusercontent.com/aliercankonus/signal-desk-prediction/'+commit+'/ops/bridge_one_shot/'+file
        with urllib.request.build_opener(NoRedirect).open(url,timeout=15) as response:data=response.read(65537)
    finally:signal.alarm(0);signal.signal(signal.SIGALRM,previous)
    if not data or len(data)>65536 or hashlib.sha256(data).hexdigest()!=digest:raise Stop('PUBLIC_DIGEST')
    module=types.ModuleType('_reviewed_cleanup_'+name)
    exec(compile(data,'<reviewed-'+file+'>','exec'),module.__dict__)
    return module


def owned(rows,attempt):
    if not isinstance(rows,list) or len(rows)!=6:raise Stop('OWNED_INVENTORY')
    groups={}
    for row in rows:
        if not isinstance(row,dict) or set(row)!={'kind','ident','proof'} or row['proof']!=attempt:raise Stop('OWNED_PROOF')
        kind,ident=row['kind'],row['ident']
        if kind not in ('worker','proxy','network','firewall','enrollment') or not isinstance(ident,str):raise Stop('OWNED_KIND')
        if kind in ('worker','proxy','network') and not re.fullmatch('[0-9a-f]{64}',ident):raise Stop('OWNED_ID')
        if kind=='firewall' and ident!='SD_ONCE_IN':raise Stop('OWNED_FIREWALL')
        if kind=='enrollment' and not re.fullmatch('[1-9][0-9]{0,19}',ident):raise Stop('OWNED_ENROLLMENT')
        groups.setdefault(kind,[]).append(ident)
    if {k:len(v) for k,v in groups.items()}!={'worker':1,'proxy':1,'network':2,'firewall':1,'enrollment':1}:raise Stop('OWNED_COUNTS')
    if len(set(x for v in groups.values() for x in v))!=6:raise Stop('OWNED_DUPLICATE')
    return groups


def firewall_references(text):
    jumps=[]
    for line in text.splitlines():
        parts=shlex.split(line)
        if '-j' not in parts:continue
        target=parts[parts.index('-j')+1]
        if target not in ('SD_ONCE_IN','SD_ONCE_FWD'):continue
        expected=['-A','INPUT' if target=='SD_ONCE_IN' else 'DOCKER-USER']
        if parts[:2]!=expected or len(parts)!=8 or set(parts[2:])!={'-i','br-sd-once','-s','172.30.50.2/32','-j',target}:
            raise Stop('UNEXPECTED_FIREWALL_REFERENCE')
        jumps.append(target)
    if sorted(jumps)!=['SD_ONCE_FWD','SD_ONCE_IN']:raise Stop('FIREWALL_REFERENCE_COUNT')


def load(workspace,auth,task,diag):
    w,raw,text=diag.inspect(workspace)
    diagnostic=json.loads(text)
    if (diagnostic['queue']['invocations']!=1 or diagnostic['queue']['status']!='blocked' or
        diagnostic['bridge']['status']!='blocked' or diagnostic['bridge']['failure']!=dict(category='child_nonzero',
            duration_ms=19067,exit_code=1,signal=None,stage='child_invocation',stop_reason='exit_nonzero')):
        raise Stop('CONSUMED_RUN_CHANGED')
    receipt=json.loads(auth.blob(w/(ATTEMPT+'-issue43-diagnostic-report-receipt')))
    if receipt.get('id')!=6778310463 or receipt.get('verified') is not True or receipt.get('body_sha256')!=hashlib.sha256(text.encode()).hexdigest():
        raise Stop('DIAGNOSTIC_RECEIPT_CHANGED')
    bundle=Path(raw['bundle']);auth.root_dir(bundle)
    exposed={'worker_probe.py','connect_proxy.py','worker_credential.py','worker_preflight.py'}
    for name,digest in auth.RELEASE.items():
        path=bundle/Path(name).name
        if hashlib.sha256(auth.blob(path,mode=0o444 if path.name in exposed else 0o600)).hexdigest()!=digest:
            raise Stop('FROZEN_BUNDLE_DIGEST')
    for name in ('operator_lifecycle','root_signer'):auth.protected_module(name,bundle/(name+'.py'))
    host=auth.protected_module('_protected_cleanup_host',bundle/'operator_host_v2.py')
    plan=host.load_plan(w/(ATTEMPT+'-runtime-v2-plan.json'))
    phase_file=plan.journal_parent/task.TASK_JOURNAL/'phase.json'
    phase_bytes=auth.blob(phase_file);phase=json.loads(phase_bytes);resources=owned(phase.get('owned'),ATTEMPT)
    if phase.get('unresolved_effect')!='one_bridge_claim' or phase.get('intent') is not None or phase.get('cleanup_verified') is not False:
        raise Stop('LIFECYCLE_CHANGED')
    inbox=plan.state/'github-inbox';host.trusted_worker_mount(inbox,10000)
    if str(inbox.lstat().st_ino)!=resources['enrollment'][0]:raise Stop('ENROLLMENT_IDENTITY')
    state_bytes=host.worker_private_bytes(inbox/'state.json',10000,8192);state=json.loads(state_bytes);claim=state.get('claim') or {}
    if (claim.get('status')!='blocked' or claim.get('queue_id')!=diag.QUEUE or claim.get('grant_id')!=6777657372 or
        claim.get('instruction_id')!=6775497757 or claim.get('publication_intent') is not None):raise Stop('CLAIM_UNRESOLVED')
    auth._original_mounts=auth.mounts;auth.mounts=lambda p,s:task.task_mounts(auth,p,s)
    deadline=time.monotonic()+600
    ops=host.HostOperations(plan,runner=host.CommandRunner(deadline=deadline),deadline=deadline)
    ops.worker_id=resources['worker'][0];ops.proxy_id=resources['proxy'][0]
    for ident in resources['network']:
        rows=json.loads(ops._docker('network','inspect',ident,timeout=10))
        if len(rows)!=1 or rows[0].get('Id')!=ident:raise Stop('NETWORK_IDENTITY')
        row=rows[0];labels=row.get('Labels') or {};role=labels.get('com.docker.compose.network')
        if role not in ('worker_isolated','proxy_uplink') or role in ops.network_ids or labels.get('org.signal-desk.issue41.attempt')!=ATTEMPT:
            raise Stop('NETWORK_SCOPE')
        wanted={ops.worker_id,ops.proxy_id} if role=='worker_isolated' else {ops.proxy_id}
        if set(row.get('Containers') or {})!=wanted:raise Stop('NETWORK_PEERS')
        ops.network_ids[role]=ident
    auth.configure(ops,phase_file.parent/'compose.issue43-once.json')
    # Complete UID/image/capability/mount/environment/peer verification before any mutation.
    ops._container(ops.worker_id,'inbox-worker',running=True)
    ops._container(ops.proxy_id,'connect-proxy',running=True)
    ops._call(['bash',plan.bundle/'worker_firewall.sh','status'],timeout=30)
    firewall_references(ops._call(['iptables','-S'],timeout=20))
    return w,ops,phase_file,phase_bytes,inbox/'state.json',state_bytes


def exact_container(ops,auth,ident,service,running):
    lines=ops._docker('inspect','--type','container','--format',auth.FORMAT,ident,timeout=10).splitlines()
    if len(lines)!=len(auth.SELECT):raise Stop('CONTAINER_INSPECTION')
    auth.confined(dict(zip(auth.SELECT,map(json.loads,lines))),ident,service,ops.plan,running)


def cleanup(ops,auth,write):
    # No worker exec or worker code is used, including to disable intake. Stopping
    # and removing the only exact runtime leaves the preserved inbox flag inert.
    before_containers=ops._docker('ps','-aq','--no-trunc',timeout=10).splitlines()
    before_networks=ops._docker('network','ls','-q','--no-trunc',timeout=10).splitlines()
    wanted_containers={ops.worker_id,ops.proxy_id};wanted_networks=set(ops.network_ids.values())
    if not wanted_containers.issubset(set(before_containers)) or not wanted_networks.issubset(set(before_networks)):
        raise Stop('BASELINE_IDS')
    write('baseline',dict(containers=before_containers,networks=before_networks))
    for role,ident,service in (('worker',ops.worker_id,'inbox-worker'),('proxy',ops.proxy_id,'connect-proxy')):
        exact_container(ops,auth,ident,service,True)
        write('stop-'+role+'-intent',dict(id=ident))
        ops._docker('stop','--time','5',ident,timeout=20)
        exact_container(ops,auth,ident,service,False)
        write('stop-'+role+'-verified',dict(id=ident))
        write('remove-'+role+'-intent',dict(id=ident))
        ops._docker('rm',ident,timeout=20)
        if ident in ops._docker('ps','-aq','--no-trunc',timeout=10).splitlines():raise Stop('CONTAINER_REMOVAL_UNVERIFIED')
        write('remove-'+role+'-verified',dict(id=ident))
        if role=='worker':
            firewall_references(ops._call(['iptables','-S'],timeout=20))
            ops._call(['bash',ops.plan.bundle/'worker_firewall.sh','status'],timeout=30)
            write('firewall-rollback-intent',dict(scope='SD_ONCE'))
            ops._call(['bash',ops.plan.bundle/'worker_firewall.sh','rollback'],timeout=40,
                env={'AUTODEV_FIREWALL_APPROVED':'yes-for-reviewed-network'})
            if 'SD_ONCE_IN' in ops._call(['iptables','-S']) or 'SD_ONCE_FWD' in ops._call(['iptables','-S']):raise Stop('FIREWALL_ROLLBACK_UNVERIFIED')
            write('firewall-rollback-verified',dict(scope='SD_ONCE'))
    for role in ('worker_isolated','proxy_uplink'):
        ops._network(role) # Frozen helper verifies exact labels/subnet/empty peers.
        ident=ops.network_ids[role];write('remove-'+role+'-intent',dict(id=ident))
        ops._docker('network','rm',ident,timeout=20)
        write('remove-'+role+'-verified',dict(id=ident))
    after_containers=ops._docker('ps','-aq','--no-trunc',timeout=10).splitlines()
    after_networks=ops._docker('network','ls','-q','--no-trunc',timeout=10).splitlines()
    if (set(after_containers)!=set(before_containers)-wanted_containers or
        set(after_networks)!=set(before_networks)-wanted_networks):raise Stop('UNRELATED_RESOURCE_BASELINE_CHANGED')
    write('runtime-cleanup-verified',dict(containers_removed=2,networks_removed=2,scoped_firewall_removed=True))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--workspace',required=True);p.add_argument('--cleanup',action='store_true');args=p.parse_args()
    try:
        auth,task,diag=public('auth'),public('task'),public('diag')
        w,ops,phase_file,phase_bytes,inbox_file,inbox_bytes=load(args.workspace,auth,task,diag)
        if not args.cleanup:print('CLEANUP: VERIFIED_IDENTITIES_ONLY; no runtime changes');return 0
        root=w/(ATTEMPT+'-exact-cleanup-01');os.mkdir(root,0o700)
        parent_fd=os.open(w,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:os.fsync(parent_fd)
        finally:os.close(parent_fd)
        def write(name,data):diag.fresh_json(root/(name+'.json'),data)
        write('scope',dict(attempt=ATTEMPT,queue_id=diag.QUEUE,run_id=diag.RUN,retry=False,
            worker=ops.worker_id,proxy=ops.proxy_id,networks=ops.network_ids,
            original_phase_sha256=hashlib.sha256(phase_bytes).hexdigest(),
            original_inbox_sha256=hashlib.sha256(inbox_bytes).hexdigest()))
        cleanup(ops,auth,write)
        if auth.blob(phase_file)!=phase_bytes or ops.plan.state/'github-inbox'!=inbox_file.parent or ops.plan.uid!=10000:
            raise Stop('ORIGINAL_JOURNAL_CHANGED')
        if ops.plan.state/'github-inbox'==inbox_file.parent and ops.plan.uid==10000:
            # All worker processes are gone. The preserved inbox/claim is never
            # rewritten or represented as resolved/ready for another task.
            if diag.read_bytes(inbox_file,10000,8192)!=inbox_bytes:raise Stop('CLAIM_BYTES_CHANGED')
        import root_signer
        text=json.dumps(dict(cleanup='issue43-exact-runtime-v1',queue_id=diag.QUEUE,run_id=diag.RUN,
            cleanup_verified=True,containers_removed=2,networks_removed=2,scoped_firewall_removed=True,
            original_unresolved_claim_preserved=True,inbox_flag_preserved_inert=True,retry=False,timer=False),sort_keys=True,separators=(',',':'))
        write('report-intent',dict(body_sha256=hashlib.sha256(text.encode()).hexdigest()))
        client=root_signer.GitHub(ops.plan.signer_token,deadline=time.monotonic()+90)
        ident=client.publish(41,text);row=client.comment(41,ident)
        if row.get('id')!=ident or row.get('body')!=text or row.get('issue_url')!='https://api.github.com/repos/aliercankonus/signal-desk-prediction/issues/41':raise Stop('REPORT_UNVERIFIED')
        write('report-receipt',dict(id=ident,verified=True))
        print('OWN_RUNTIME_CLEANUP: EXACT_IDS_VERIFIED')
        print('HISTORY_AUTH_CLAIM: PRESERVED; no retry, model, dispatch or timer')
        print('GITHUB_CLEANUP_REPORT: '+str(ident));return 0
    except (Exception,KeyboardInterrupt) as exc:
        code=str(exc) if isinstance(exc,Stop) and re.fullmatch('[A-Z0-9_]{1,80}',str(exc)) else 'UNVERIFIED_PRESERVE'
        print('STOP: EXACT_CLEANUP '+code+'; preserve state; no retry or guessed cleanup');return 1

if __name__=='__main__':raise SystemExit(main())
