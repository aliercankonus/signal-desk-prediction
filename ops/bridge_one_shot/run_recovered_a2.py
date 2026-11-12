"""Dormant root caller for the previously approved, unclaimed a2 instruction.
Default does nothing. No operator handoff is valid before complete review/CI.
"""
import argparse
from dataclasses import replace,fields
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import sys
import types
import urllib.request

SOURCE='c12a60ca1c265e4b7085027bf809234367db07b2'
INSTRUCTION=6824067293
DIRECTORY='issue43-a2-integration-01'
REPO='aliercankonus/signal-desk-prediction'
# Gate digest is fixed before the release is published.
GATE_SHA='9848357f0a414075008e33b5b7df260d197054f82d1c23244eb71b350761f480'


def public(commit,path,digest):
    if not re.fullmatch('[0-9a-f]{40}',commit) or not re.fullmatch('[0-9a-f]{64}',digest):raise ValueError('source identity')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*a,**kw):raise ValueError('redirect')
    if signal.getitimer(signal.ITIMER_REAL)[0]:raise ValueError('existing timer')
    before=signal.getsignal(signal.SIGALRM)
    def timeout(*a):raise TimeoutError()
    signal.signal(signal.SIGALRM,timeout);signal.alarm(20)
    try:
        with urllib.request.build_opener(NoRedirect).open('https://raw.githubusercontent.com/'+REPO+'/'+commit+'/'+path,timeout=15) as r:data=r.read(65537)
    finally:signal.alarm(0);signal.signal(signal.SIGALRM,before)
    if not data or len(data)>65536 or hashlib.sha256(data).hexdigest()!=digest:raise ValueError('source digest')
    return data


def module(name,data):
    result=types.ModuleType(name);sys.modules[name]=result
    exec(compile(data,'<hash-verified-source>','exec'),result.__dict__);return result


def integrate(w,plan,old,*,a2,auth,host,cleanup,readback,signer,scope,row,root=None):
    """One-way root preparation followed by the unchanged frozen lifecycle.
    Never calls staging/clone/login enrollment entry or clears an old journal.
    """
    root=root or w/DIRECTORY
    a2.mkdir(root)  # Exclusive durable directory; partial state never resumes.
    a2.put(root/'intent.json',dict(schema=1,instruction_id=INSTRUCTION,task='one-approved-a2',retry=False))
    a2.mkdir(root/'helpers');a2.mkdir(root/'journals')
    for name in ('capture','factory','write_root'):
        path=w/a2.ATTEMPT/'helpers'/(name+'.py')
        raw=auth.blob(path,mode=0o444)
        expected={'capture':'2ba3939448ee00197b09907675c4949bad12b2202680893d378dc72c46d5fc63',
          'factory':'38a3f09dc30e699c66e64843dd9f8a37c744a87413c1ba9af12fa5f1e708fe30',
          'write_root':'7f62b3ad4ba638d29756b962a44d22736c46f5371d238f78550df53f0aaf859f'}[name]
        if hashlib.sha256(raw).hexdigest()!=expected:raise ValueError('worker overlay digest')
        a2.put(root/'helpers'/(name+'.py'),raw,mode=0o444)
    a2.put(root/'helpers'/'worker-preflight-v3.py',auth.WORKER_PREFLIGHT_V3,mode=0o444)
    plan=replace(plan,journal_parent=root/'journals')
    a2.put(root/'plan.json',{f.name:str(getattr(plan,f.name)) if isinstance(getattr(plan,f.name),Path) else getattr(plan,f.name) for f in fields(plan)})
    ops=a2.configure(root,plan,old,host,auth,cleanup,readback,signer,INSTRUCTION,row,scope)
    # Host login is only owner/CLI/context preflight; no device authentication.
    journal=host.Journal(plan.journal_parent/'approved-runtime-01',plan.attempt)
    previous=signal.getsignal(signal.SIGTERM)
    def interrupted(*a):raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM,interrupted)
    try:return host.run_once(journal,ops,deadline=ops.deadline)
    finally:signal.signal(signal.SIGTERM,previous)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--workspace');p.add_argument('--execute-approved-once',action='store_true');args=p.parse_args()
    if not args.execute_approved_once:print('REVIEW ONLY: no host, GitHub, credential or runtime action');return 0
    phase='inputs'
    try:
        if os.geteuid()!=0 or not sys.stdin.isatty():raise ValueError('root terminal')
        w=Path(args.workspace)
        if not w.is_absolute() or '..' in w.parts:raise ValueError('workspace')
        if os.path.lexists(w/DIRECTORY):raise FileExistsError('preserve integration')
        phase='verified-source'
        a2=module('_recovered_a2',public(SOURCE,'ops/bridge_one_shot/attempt_a2.py','211867c828edc0d18f493790665c688c90edcd3d0cf6246b8ae47e099ed2ca54'))
        blobs=a2.release(SOURCE,'88fc917ddd132bfed497216c97df35a9f025d5c0cc56b0cbbb8b03a51e61e353')
        auth=module('_recovered_auth',blobs['auth']);auth.root_dir(w)
        recovery=module('_recovered_object_v2',public('c740da7fd33264a80e891b8bc6397a6e81be75fb','ops/bridge_one_shot/prepare_a2_object_clone_v2.py','df8834dd948a32845a4e2451774ebb98758888c3b9c678087b0338b15ca06387'))
        gate=module('_recovered_gate',public('fc2f40385a333b2769d96f84327f4e3f83ba0305','ops/bridge_one_shot/recovered_runner_binding.py',GATE_SHA))
        bundle=w/(a2.OLD+'-runtime-v2-bundle');auth.root_dir(bundle)
        for filename in ('operator_lifecycle.py','operator_host_v2.py'):
            if hashlib.sha256(auth.blob(bundle/filename)).hexdigest()!=auth.RELEASE['ops/bridge_one_shot/'+filename]:raise ValueError('frozen root digest')
        auth.protected_module('operator_lifecycle',bundle/'operator_lifecycle.py')
        signer=module('root_signer',blobs['signer']);host=auth.protected_module('_recovered_host',bundle/'operator_host_v2.py')
        host.check_signer_binding=lambda plan,scope:a2.binding(plan,scope,host,auth)
        old=host.load_plan(w/(a2.OLD+'-runtime-v2-plan.json'))
        phase='recovered-binding'
        client=signer.GitHub(old.signer_token)
        plan=gate.bind(w,old,host=host,recovery=recovery,a2=a2,client=client)
        prefix='/repos/'+REPO
        if client.get(prefix+'/git/ref/heads/issue43-one-shot-a2')!={'missing':True} or client.get(prefix+'/pulls?state=all&head=aliercankonus%3Aissue43-one-shot-a2&per_page=2')!=[]:raise ValueError('task branch or PR exists')
        scope=signer.load_scope(plan.signer_policy);row=a2.instruction(client,INSTRUCTION)
        phase='one-way-integration'
        result=integrate(w,plan,old,a2=a2,auth=auth,host=host,cleanup=module('_recovered_cleanup',blobs['cleanup']),
            readback=module('_recovered_readback',blobs['readback']),signer=signer,scope=scope,row=row)
        print('RECOVERED_A2_RESULT: '+result['status'])
        print('CLEANUP_VERIFIED: '+str(result['cleanup_verified']))
        print('GITHUB_REPORT: '+str(result['report_receipt']))
        return 0 if result['status']=='review-ready' and result['cleanup_verified'] else 2
    except (Exception,KeyboardInterrupt) as exc:
        print('STOP: RECOVERED_A2 PHASE='+phase+' TYPE='+type(exc).__name__+'; preserve all state; no retry or cleanup');return 1

if __name__=='__main__':raise SystemExit(main())
