"""Explicit operator-only v2 preparation; no Docker, auth, network changes or tasks.

--prepare performs public source retrieval and private filesystem provisioning,
including the separately approved worker credential copy. Default is metadata only.
Never invoked by manager automation. No overwrite, retry, cleanup or old-spec edit.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import time
import types
import urllib.request

REPO = 'aliercankonus/signal-desk-prediction'
ATTEMPT = 'issue41-cold-20261110-01'
RELEASE_HASH = '6b7547003d822802a288a22b7da5f1a61f7c367fbbfcbf4aa88b944925171aae'
DEPS = {
 'probe_worker_runtime.py':('76a4b5f4dcf92ad57eae1c693aa2272ade10a8ab','01361b11b151f7f61c2ad6c2a17ba9937dea0c61be25828ea120baf4aa476f16'),
 'operator_bootstrap_v5.py':('674392d6cd87e1c440d1dc7eec916fcb6882b545','d0ae47d12190bb2b400e99181f4802fe291698924b92df7ca499b39834bb84f3')}


class Stop(Exception): pass


def fetch(commit, path):
    if (not re.fullmatch('[0-9a-f]{40}',commit) or
        not re.fullmatch(r'ops/(bridge_one_shot|github_inbox)/[A-Za-z0-9_.-]+',path)):
        raise Stop('PUBLIC_SOURCE_PATH')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*a,**kw): raise Stop('PUBLIC_SOURCE_REDIRECT')
    if signal.getitimer(signal.ITIMER_REAL)[0]: raise Stop('EXISTING_TIMER')
    def expired(*_): raise TimeoutError()
    previous=signal.signal(signal.SIGALRM,expired);signal.alarm(20)
    try:
        with urllib.request.build_opener(NoRedirect).open(
            'https://raw.githubusercontent.com/'+REPO+'/'+commit+'/'+path,timeout=15) as response:
            data=response.read(65537)
    finally:
        signal.alarm(0);signal.signal(signal.SIGALRM,previous)
    if len(data)>65536: raise Stop('PUBLIC_SOURCE_SIZE')
    return data


def checked(getter,commit,path,digest):
    data=getter(commit,path)
    if len(data)>65536 or hashlib.sha256(data).hexdigest()!=digest:raise Stop('PUBLIC_SOURCE_DIGEST')
    return data


def module(name,data):
    m=types.ModuleType(name)
    exec(compile(data,'<reviewed-'+name+'>','exec'),m.__dict__)
    return m


def load_inputs(workspace,commit,getter):
    if not re.fullmatch('[0-9a-f]{40}',commit):raise Stop('PUBLIC_SOURCE_COMMIT')
    modules={}
    for name,(pin,digest) in DEPS.items():
        modules[name]=module(name,checked(getter,pin,'ops/bridge_one_shot/'+name,digest))
    probe=modules['probe_worker_runtime.py'];boot=modules['operator_bootstrap_v5.py']
    w,cfg=probe.inputs(workspace)
    release=json.loads(checked(getter,commit,'ops/bridge_one_shot/runtime_v2_release.json',RELEASE_HASH))
    if (set(release)!={'schema','from_adapter','runner_commit','files'} or release['schema']!=2 or
        release['from_adapter']!=boot.MERGE or release['runner_commit']!=boot.RUNNER_PIN or
        not isinstance(release['files'],dict) or len(release['files'])!=13 or
        any(not re.fullmatch(r'ops/(bridge_one_shot|github_inbox)/[A-Za-z0-9_.-]+',p) or
            not re.fullmatch('[0-9a-f]{64}',h) for p,h in release['files'].items())):
        raise Stop('RELEASE_SCOPE')
    return probe,boot,w,cfg,release


def provision(probe,boot,w,cfg,release,commit,*,apply=False,getter=fetch,source_fetch=None):
    """Dependency seam is for offline tests; CLI uses only fixed production paths."""
    if os.geteuid()!=0:raise Stop('ROOT_REQUIRED')
    boot.STAGING_DEADLINE=time.monotonic()+600
    suffix=ATTEMPT+'-runtime-v2'
    destinations={k:w/(suffix+'-'+k) for k in ('bundle','auth','home')}
    plan_path=w/(suffix+'-plan.json');intent_path=w/(suffix+'-intent.json');receipt_path=w/(suffix+'-receipt.json')
    if any(os.path.lexists(p) for p in (*destinations.values(),plan_path,intent_path,receipt_path)):
        raise Stop('V2_ALREADY_PRESENT_PRESERVE')
    # A successful #68 probe is a consumed, preserved operator receipt. Do not
    # rerun it or infer authentication from it; accept only the recorded scope.
    runtime=json.loads(probe.read_root(w/(ATTEMPT+'-runtime-probe-01-receipt.json')))
    r=runtime.get('result') or {}
    if (runtime.get('schema')!=1 or runtime.get('probe')!=ATTEMPT+'-runtime-probe-01' or
        runtime.get('cleanup_verified') is not True or runtime.get('interrupted_or_error') is not False or
        runtime.get('credentials_installed') is not False or runtime.get('task_authority') is not False or
        r!={'schema':1,'worker_identity':True,'git_available':True,'gh_available':False,'hermes_available':True,
            'runner_head':True,'runner_clean':True,'test_versions':['3.14.9','8.3.3'],'versions_match':True,'capability_pass':False}):
        raise Stop('CAPABILITY_RECEIPT_SCOPE')
    # Guard actual existing source and empty queue/claim/runtime journals before
    # effects. No Git command ever targets the worker-owned runner.
    source=Path(cfg['source']);probe.root_dir(source);boot._config_names_only(source)
    before=boot._git_snapshot(source)
    if any(line.split(b' ',1)[0].startswith(b'refs/replace/') for line in before[0].splitlines()):
        raise Stop('SOURCE_REPLACEMENT_REF')
    for p in (Path(cfg['state'])/'queue',Path(cfg['journal_parent']),Path(cfg['signer_state_root'])):
        s=p.lstat()
        if not stat.S_ISDIR(s.st_mode) or s.st_mode&0o077 or any(p.iterdir()):raise Stop('EXISTING_RUNTIME_STATE')
    if os.path.lexists(Path(cfg['state'])/'github-inbox'):raise Stop('EXISTING_INBOX_STATE')
    public=probe.read_root(w/'manager-public.pem',8192)
    records=boot.build_records(cfg,public)
    for p,data in ((Path(cfg['auth'])/'authorization.json',records['authorization.json']),
                   (Path(cfg['home'])/'config.yaml',records['provider-config.yaml'])):
        boot._regular(p,10000)
        # These are nonsecret, deterministic old staged records. Never read any
        # profile/store/credential as a substitute for this exact expected file.
        expected=(json.dumps(data,sort_keys=True,separators=(',',':')).encode()+b'\n') if isinstance(data,dict) else data
        fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        with os.fdopen(fd,'rb') as f:
            if f.read(8193)!=expected:raise Stop('ORIGINAL_STAGING_CHANGED')
    if set(p.name for p in Path(cfg['auth']).iterdir())!={'authorization.json'} or set(p.name for p in Path(cfg['home']).iterdir())!={'config.yaml'}:
        raise Stop('ORIGINAL_AUTH_HOME_NOT_EMPTY')
    boot._regular(w/'worker-github-token',0,limit=512)  # metadata only before explicit provisioning
    if not apply:
        print('V2_PREPARATION: REVIEW_ONLY; no writes or credential read');return
    probe.exclusive(intent_path,{'schema':2,'source_commit':commit,'from_adapter':boot.MERGE,
        'runner_commit':boot.RUNNER_PIN,'activation':False,'task_authority':False})
    blobs={p:checked(getter,commit,p,h) for p,h in release['files'].items()}
    inventory=json.loads(blobs['ops/bridge_one_shot/operator_artifacts_v2.json'])
    if inventory!={'schema':2,'runner_commit':boot.RUNNER_PIN,'files':sorted(blobs)}:raise Stop('ARTIFACT_INVENTORY')
    if source_fetch:
        source_fetch(source,commit)  # offline seam only
    else:
        env={'PATH':boot.PATH,'HOME':'/nonexistent','LC_ALL':'C','GIT_CONFIG_NOSYSTEM':'1',
             'GIT_CONFIG_GLOBAL':'/dev/null','GIT_TERMINAL_PROMPT':'0','GIT_ASKPASS':'/bin/false',
             'SSH_ASKPASS':'/bin/false','GIT_NO_LAZY_FETCH':'1','GIT_NO_REPLACE_OBJECTS':'1'}
        boot._bounded_run(['/usr/bin/git',*boot.LOCAL_OPTIONS,'-c','protocol.https.allow=always',
            '-c','http.followRedirects=false','--git-dir='+str(source),'fetch','--no-tags',
            '--no-write-fetch-head','--no-recurse-submodules','--no-auto-maintenance','--refmap=',
            'https://github.com/'+REPO+'.git',commit],timeout=90,env=env)
    if boot._git_snapshot(source)!=before:raise Stop('SOURCE_REFS_CHANGED_PRESERVE')
    for path,blob in blobs.items():
        if boot._local_git(source,('show',commit+':'+path))!=blob:raise Stop('SOURCE_BLOB_MISMATCH')
    for key,p in destinations.items():boot._mkdir(p,0 if key=='bundle' else 10000,0 if key=='bundle' else 10000)
    exposed={'worker_probe.py','connect_proxy.py','worker_credential.py','worker_preflight.py'}
    for path,blob in blobs.items():
        p=destinations['bundle']/Path(path).name;boot._write(p,blob,0,0)
        if p.name in exposed:p.chmod(0o444)
    boot._write(destinations['bundle']/'merged-byte-manifest.json',{'schema':1,'merge':commit,'sha256':release['files']},0,0)
    boot._write(destinations['auth']/'authorization.json',records['authorization.json'],10000,10000)
    boot._write(destinations['home']/'config.yaml',records['provider-config.yaml'],10000,10000)
    credential=module('reviewed_worker_credential',blobs['ops/github_inbox/worker_credential.py'])
    boot._write(destinations['home']/'gitconfig',credential.GITCONFIG.encode(),10000,10000)
    # Explicit operator --prepare only. No value printed, passed as an argument,
    # embedded in gitconfig, committed, or copied from an old auth profile.
    token=probe.read_root(w/'worker-github-token',512)
    if not re.fullmatch(rb'github_pat_[A-Za-z0-9_]{32,500}',token):raise Stop('WORKER_CREDENTIAL_FORMAT')
    boot._write(destinations['auth']/'github-token',token,10000,10000)
    (destinations['auth']/'github-token').chmod(0o400)
    token=None
    plan={k:cfg[k] for k in boot.PLAN_KEYS}
    plan.update({k:str(p) for k,p in destinations.items()});plan['merge']=commit
    boot._write(plan_path,plan,0,0)
    probe.exclusive(receipt_path,{'schema':2,'source_commit':commit,'from_adapter':boot.MERGE,
        'runner_commit':boot.RUNNER_PIN,'source_refs_preserved':True,'original_staging_preserved':True,
        'worker_credential_installed':True,'provider_authentication':False,'activation':False,
        'manager_exclusive_invocation':'UNPROVEN','runtime_authority':False,'task_authority':False})
    print('RUNTIME_V2: PREPARED_NO_ACTIVATION')
    print('ORIGINAL_STAGING_SOURCE_REFS: PRESERVED')
    print('WORKER_GIT_CREDENTIAL: INSTALLED_DEDICATED_READ_ONLY')
    print('PROVIDER_AUTH_SERVICES_TASKS: NOT_STARTED')
    print('OVERALL: NO-GO — isolation/manager authority and provider authentication remain separate')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace',required=True);parser.add_argument('--source-commit',required=True)
    parser.add_argument('--prepare',action='store_true');args=parser.parse_args()
    previous=signal.getsignal(signal.SIGTERM)
    def interrupted(*_):raise InterruptedError()
    signal.signal(signal.SIGTERM,interrupted)
    try:
        probe,boot,w,cfg,release=load_inputs(args.workspace,args.source_commit,fetch)
        provision(probe,boot,w,cfg,release,args.source_commit,apply=args.prepare)
        return 0
    except (Exception,KeyboardInterrupt) as exc:
        code=str(exc) if isinstance(exc,Stop) and re.fullmatch('[A-Z0-9_]{1,80}',str(exc)) else 'PRESERVE_STATE'
        print('STOP: RUNTIME_V2_PREPARATION '+code+'; preserve all files; no retry or cleanup')
        return 1
    finally:signal.signal(signal.SIGTERM,previous)


if __name__=='__main__':raise SystemExit(main())
