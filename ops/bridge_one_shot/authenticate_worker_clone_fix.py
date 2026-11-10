"""Reviewed clone-key correction for the unfinished authentication-only boundary.

--authenticate requires separately authorized host network/firewall/container and
provider authentication actions. Manager automation must never invoke it on a VPS.
Review/default only validates protected files. A flag is not isolation or authority.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import time
import types
import termios

ATTEMPT = 'issue41-cold-20261110-01'
SOURCE = '42db985bba2f0a64ce8d848e39a11c2a18c689f3'
RUNNER = 'e84021a786004456a12de9e25eae50d191da6cf1'
RELEASE = {'ops/bridge_one_shot/bridge_readback.py': '47c90fd8dc1f77c8d0d942fe499764b145d10dcc74e51271aac713f4143dbb6c', 'ops/bridge_one_shot/compose.operator.v2.yml': 'f8b710df1ac286b09ff28364dce8327db0b5c6d14ae2a153ac354daa8af36460', 'ops/bridge_one_shot/connect_proxy.py': 'ccf1d660fba5a4758608b34611f395e5460e148c3e1f67edaa25529b5c78d619', 'ops/bridge_one_shot/network_preflight.py': 'fb3520f6de9c66c6bbcb743fd600ba589d3b0126d7b10ba26ec93137cc393402', 'ops/bridge_one_shot/network_resources.py': '52b1c192ef6a366b0ec16e0ffa0c07697274d39b1a98e581cb796e99165f7b1d', 'ops/bridge_one_shot/operator_artifacts_v2.json': '4dcfbef0f2caef80bfc1430ef187f3d6fd88858ba682832a11d913aeb67e41b3', 'ops/bridge_one_shot/operator_host_v2.py': 'efb54acb6a1cb80642aec0861c2e81ce67c0dc7ebf92bbaf368d7b00affede81', 'ops/bridge_one_shot/operator_lifecycle.py': 'f09dbbcb6cd02eb6ab3823d24e97292ba6ba38135ddb48df9f3248b25e00ccf9', 'ops/bridge_one_shot/worker_firewall.sh': '9299f879861980389bcccf1c3afd0f7792a857ad6baa9c1ee287f4d0f4304da4', 'ops/github_inbox/root_signer.py': 'd7d9cae83ae0e0b728574b998f9241df9f6e12c51e12ed87025cfce1916d61fd', 'ops/github_inbox/worker_credential.py': '405d1ef620da69dd8e2dff4606f22671121ef0be91fb562b3eec504d925cde77', 'ops/github_inbox/worker_preflight.py': '8d67c19e04df306888ce03a8aad333b4d1ff99176bea8f85695f1b2efe8a10f4', 'ops/github_inbox/worker_probe.py': '649fb748028750f70e6ba06ad442cbec6d0ce1793a69643995d63c4dc9dba0b9'}
IMAGE_ENV = set('PATH PYTHONUNBUFFERED PYTHONDONTWRITEBYTECODE PLAYWRIGHT_BROWSERS_PATH HERMES_RUNTIME_DIR HERMES_PYTHON CC CXX HERMES_WEB_DIST HERMES_TUI_DIR HERMES_HOME HERMES_WRITE_SAFE_ROOT XDG_RUNTIME_DIR HOME'.split())
TMPFS = {'/tmp':'rw,nosuid,nodev,size=64m',
         '/opt/data':'rw,noexec,nosuid,nodev,size=1m,mode=0755',
         '/home':'rw,noexec,nosuid,nodev,size=1m,mode=0755',
         '/root':'rw,noexec,nosuid,nodev,size=1m,mode=0700'}
PROVIDER = ('hermes','auth','add','openai-codex','--type','oauth','--no-browser','--timeout','480')
RESERVE = 420
CORRECTED_JOURNAL = ATTEMPT+'-auth-only-02'
WORKER_PREFLIGHT_V3 = "\"\"\"Actual worker owner/config check before provider handoff; no credential GET.\"\"\"\nimport json\nimport os\nfrom pathlib import Path\nimport subprocess\nimport stat\nimport resource\nimport tempfile\nimport re\n\nclass PreflightBlocked(Exception): pass\n\n\ndef tracking_keys(keys, call):\n    allowed = {'core.repositoryformatversion','core.filemode','core.bare','core.logallrefupdates',\n               'remote.origin.url','remote.origin.fetch','user.name','user.email'}\n    pairs = {}\n    for key in keys:\n        if key in allowed: continue\n        match = re.fullmatch(r'branch\\.([A-Za-z0-9][A-Za-z0-9._/-]{0,127})\\.(remote|merge)', key)\n        if not match: raise PreflightBlocked('LOCAL_CONFIG_KEY')\n        branch, field = match.groups()\n        if key in pairs: raise PreflightBlocked('DUPLICATE_TRACKING_KEY')\n        pairs[key] = (branch, field)\n    for key,(branch,field) in pairs.items():\n        if not all('branch.'+branch+'.'+suffix in pairs for suffix in ('remote','merge')):\n            raise PreflightBlocked('INCOMPLETE_TRACKING_PAIR')\n        expected = b'origin\\n' if field=='remote' else ('refs/heads/'+branch+'\\n').encode('ascii')\n        if call(['config','--local','--no-includes','--get-all',key]) != expected:\n            raise PreflightBlocked('TRACKING_VALUE')\n\nPIN = 'e84021a786004456a12de9e25eae50d191da6cf1'\nHELPER = '!/opt/hermes/.venv/bin/python -I -B /opt/worker-credential.py'\nHELPER_MODULE = '/opt/worker-credential.py'\n\n\ndef check(runner=Path('/workspace/runner'), config=Path('/worker-home/gitconfig'), call=None):\n    if os.getuid() != 10000 or os.getgid() != 10000: raise PermissionError('worker owner')\n    def run(parts):\n        env = {'PATH':'/usr/bin:/bin','HOME':'/worker-home','GIT_CONFIG_NOSYSTEM':'1',\n               'GIT_CONFIG_GLOBAL':'/dev/null','GIT_NO_LAZY_FETCH':'1','GIT_NO_REPLACE_OBJECTS':'1',\n               'GIT_TERMINAL_PROMPT':'0'}\n        def bounded_output():resource.setrlimit(resource.RLIMIT_FSIZE,(4096,4096))\n        with tempfile.TemporaryFile() as output:\n            p = subprocess.run(['git', '--no-optional-locks', '-c', 'core.hooksPath=/dev/null',\n                            '-c', 'core.fsmonitor=false', '-C', str(runner), *parts],\n                           env=env, stdin=subprocess.DEVNULL, stdout=output,stderr=subprocess.DEVNULL,\n                           timeout=10,preexec_fn=bounded_output)\n            output.seek(0);data=output.read(4097)\n        if p.returncode or len(data) >= 4096: raise ValueError('Git unavailable')\n        return data\n    call = call or run\n    # Inspect config keys without following includes, before loading any user\n    # helper. Do not run credential fill here: this gate must precede auth use.\n    keys = call(['config','--local','--no-includes','--name-only','--list']).decode().splitlines()\n    tracking_keys(keys, call)\n    if call(['config','--local','--no-includes','--get','remote.origin.url']).strip() != b'https://github.com/aliercankonus/signal-desk-prediction.git':\n        raise ValueError('remote scope')\n    if call(['rev-parse','HEAD']).strip() != PIN.encode() or call(['status','--porcelain=v1','--untracked-files=all']):\n        raise ValueError('runner HEAD/cleanliness')\n    s = config.lstat()\n    if not stat.S_ISREG(s.st_mode) or s.st_uid != 10000 or s.st_gid != 10000 or s.st_mode & 0o077 or s.st_size > 2048:\n        raise PermissionError('Git config metadata')\n    # The root-installed helper is mounted as an immutable file at this exact\n    # path. Load only its constant template; importing it has no credential I/O.\n    import importlib.util\n    spec = importlib.util.spec_from_file_location('reviewed_worker_credential',HELPER_MODULE)\n    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)\n    fd = os.open(config, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)\n    with os.fdopen(fd, 'rb') as f:\n        opened = os.fstat(f.fileno())\n        if (opened.st_dev, opened.st_ino, opened.st_mode) != (s.st_dev,s.st_ino,s.st_mode):\n            raise ValueError('Git config changed')\n        data = f.read(2049)\n    named = config.lstat()\n    if (named.st_dev,named.st_ino,named.st_size,named.st_mtime_ns) != (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns):\n        raise ValueError('Git config changed')\n    if data != module.GITCONFIG.encode(): raise ValueError('Git helper configuration')\n    return {'worker_owner_git':True,'credential_helper_configured':True}\n\n\ndef main():\n    try:\n        print(json.dumps(check(),sort_keys=True)); return 0\n    except Exception as exc:\n        code = str(exc) if isinstance(exc, PreflightBlocked) else 'OWNER_CONFIG_UNVERIFIED'\n        print('WORKER_PREFLIGHT: BLOCKED CODE='+code); return 1\n\n\nif __name__ == '__main__': raise SystemExit(main())\n".encode('utf-8')


class Stop(Exception): pass


def root_dir(folder):
    for p in (folder,*folder.parents):
        s=p.lstat()
        if not stat.S_ISDIR(s.st_mode) or s.st_uid!=0 or s.st_mode&0o022:raise Stop('ROOT_ANCESTRY')
    if stat.S_IMODE(folder.stat().st_mode)!=0o700:raise Stop('PRIVATE_ROOT_DIRECTORY')


def blob(path, *, mode=0o600, limit=65536):
    s=path.lstat()
    if (not stat.S_ISREG(s.st_mode) or s.st_uid!=0 or stat.S_IMODE(s.st_mode)!=mode or
        s.st_nlink!=1 or not 0<s.st_size<=limit):raise Stop('PROTECTED_FILE')
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    with os.fdopen(fd,'rb') as f:
        t=os.fstat(f.fileno());data=f.read(limit+1)
    named=path.lstat()
    ident=lambda x:(x.st_dev,x.st_ino,x.st_size,x.st_mtime_ns,x.st_mode,x.st_uid,x.st_nlink)
    if not ident(s)==ident(t)==ident(named) or len(data)!=s.st_size:raise Stop('PROTECTED_FILE_CHANGED')
    return data


def protected_module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
    return module



def failure_records(receipt,phase):
    expected={'schema':1,'github_readonly_verified':False,'device_cli_success':False,
        'cleanup_verified':True,'partial_startup':False,'failure':'AUTH_ERROR_CALLEDPROCESSERROR',
        'enrollment':False,'signing':False,'dispatch':False,'timer':False,
        'model_entitlement':'UNPROVEN','manager_exclusivity':'UNPROVEN'}
    if receipt!=expected:raise Stop('PRIOR_AUTH_RESULT_REQUIRES_REVIEW')
    if (phase.get('version')!=1 or phase.get('attempt')!=ATTEMPT or phase.get('phase')!='cleanup' or
        phase.get('status')!='pending' or phase.get('intent') is not None or
        phase.get('unresolved_effect') is not None or phase.get('owned')!=[] or
        phase.get('cleanup_verified') is not True or phase.get('report_receipt') is not None):
        raise Stop('PRIOR_RUNTIME_UNRESOLVED')


def prior_failure(plan):
    previous=plan.journal_parent/(ATTEMPT+'-auth-only-01')
    if {p.name for p in plan.journal_parent.iterdir()}!={previous.name}:raise Stop('JOURNAL_HISTORY_REQUIRES_REVIEW')
    root_dir(previous)
    if {p.name for p in previous.iterdir()}!={'phase.json','compose.auth-only.json','auth-only-receipt.json'}:
        raise Stop('PRIOR_JOURNAL_INVENTORY')
    failure_records(json.loads(blob(previous/'auth-only-receipt.json')),json.loads(blob(previous/'phase.json')))


def correction_file(plan):
    return plan.journal_parent/CORRECTED_JOURNAL/'worker_preflight_v3.py'


def load(workspace):
    if os.geteuid()!=0:raise Stop('ROOT_REQUIRED')
    w=Path(workspace)
    if not w.is_absolute() or str(w)!=workspace or '..' in w.parts:raise Stop('WORKSPACE_PATH')
    root_dir(w);bundle=w/(ATTEMPT+'-runtime-v2-bundle');root_dir(bundle)
    receipt=json.loads(blob(w/(ATTEMPT+'-runtime-v2-receipt.json')))
    if (receipt.get('schema')!=2 or receipt.get('source_commit')!=SOURCE or receipt.get('runner_commit')!=RUNNER or
        receipt.get('source_refs_preserved') is not True or receipt.get('original_staging_preserved') is not True or
        receipt.get('worker_credential_installed') is not True or receipt.get('provider_authentication') is not False or
        receipt.get('activation') is not False or receipt.get('runtime_authority') is not False or receipt.get('task_authority') is not False):
        raise Stop('V2_RECEIPT_SCOPE')
    exposed={'worker_probe.py','connect_proxy.py','worker_credential.py','worker_preflight.py'}
    expected={Path(p).name for p in RELEASE}|{'merged-byte-manifest.json'}
    if {p.name for p in bundle.iterdir()}!=expected:raise Stop('BUNDLE_INVENTORY')
    for name,digest in RELEASE.items():
        data=blob(bundle/Path(name).name,mode=0o444 if Path(name).name in exposed else 0o600)
        if hashlib.sha256(data).hexdigest()!=digest:raise Stop('BUNDLE_DIGEST')
    if json.loads(blob(bundle/'merged-byte-manifest.json'))!={'schema':1,'merge':SOURCE,'sha256':RELEASE}:
        raise Stop('BUNDLE_MANIFEST')
    # Import only root-protected, digest-verified public code. No key/token store
    # is opened by these imports; no root signer, grant or report method is used.
    # The frozen adapter inserts sibling search paths. Pin its two project imports
    # explicitly so an unrelated sibling directory cannot shadow verified code.
    for name in ('operator_lifecycle','root_signer'):protected_module(name,bundle/(name+'.py'))
    host=protected_module('_reviewed_auth_host',bundle/'operator_host_v2.py')
    plan=host.load_plan(w/(ATTEMPT+'-runtime-v2-plan.json'))
    original=json.loads(blob(w/(ATTEMPT+'-bootstrap-spec.json')))
    target={f.name:original[f.name] for f in host.fields(host.Plan)}
    target.update({k:str(w/(ATTEMPT+'-runtime-v2-'+k)) for k in ('bundle','auth','home')});target['merge']=SOURCE
    if json.loads(blob(w/(ATTEMPT+'-runtime-v2-plan.json')))!=target:raise Stop('PLAN_TRANSITION')
    for path in (plan.source,plan.journal_parent,plan.signer_state_root):root_dir(path)
    for path in (plan.runner,plan.state,plan.auth,plan.context,plan.home,plan.venv,plan.inbox):
        host.trusted_worker_mount(path,10000)
        s=path.lstat()
        if s.st_uid!=10000 or s.st_gid!=10000:raise Stop('WORKER_DIRECTORY_OWNER')
    if (plan.uid,plan.gid)!=(10000,10000):raise Stop('WORKER_IDENTITY')
    if {p.name for p in plan.home.iterdir()}!={'config.yaml','gitconfig'} or {p.name for p in plan.auth.iterdir()}!={'authorization.json','github-token'}:
        raise Stop('PRIOR_AUTH_STATE_PRESERVE')
    if host.worker_private_bytes(plan.home/'config.yaml',10000)!=b'auth:\n  adopt_external_logins: false\n  codex_login_flow: device_code\n':
        raise Stop('DEVICE_ONLY_CONFIG')
    helper=types.ModuleType('_reviewed_auth_credential')
    exec(compile(blob(bundle/'worker_credential.py',mode=0o444),'<reviewed-helper>','exec'),helper.__dict__)
    if host.worker_private_bytes(plan.home/'gitconfig',10000)!=helper.GITCONFIG.encode():raise Stop('GIT_CONFIG')
    s=(plan.auth/'github-token').lstat()  # Metadata only; credential consumed only by worker Git.
    if not stat.S_ISREG(s.st_mode) or (s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode),s.st_nlink)!=(10000,10000,0o400,1):
        raise Stop('WORKER_CREDENTIAL_METADATA')
    for path in (plan.state/'queue',plan.signer_state_root):
        if path.is_symlink() or not path.is_dir() or any(path.iterdir()):raise Stop('EXISTING_RUNTIME_STATE')
    if os.path.lexists(plan.state/'github-inbox'):raise Stop('EXISTING_JOURNAL_INBOX')
    prior_failure(plan)
    return host,plan


def mounts(plan,service):
    if service=='connect-proxy':return {('/opt/connect-proxy.py',str(plan.bundle/'connect_proxy.py')):False}
    pairs=((plan.runner,'/workspace/runner'),(plan.state,'/state'),(plan.auth,'/private/auth'),
           (plan.context,'/private/context'),(plan.home,'/worker-home'),(plan.venv,'/opt/data/signal-desk-tooling/venvs/issue26-recovery-python314-20261030'),
           (plan.inbox,'/private/inbox'),(plan.bundle/'worker_probe.py','/opt/worker-probe.py'),
           (plan.bundle/'worker_credential.py','/opt/worker-credential.py'),(correction_file(plan),'/opt/worker-preflight.py'))
    return {(target,str(source)):target=='/worker-home' for source,target in pairs}


def tmpfs(service):
    result=dict(TMPFS)
    if service=='connect-proxy':result['/worker-home']='rw,noexec,nosuid,nodev,size=1m,mode=0755'
    return result


def auth_config(rendered,plan):
    if set(rendered.get('services',{}))!={'inbox-worker','connect-proxy'}:raise Stop('COMPOSE_SERVICES')
    for service,item in rendered['services'].items():
        expected=mounts(plan,service);seen=set()
        for v in item.get('volumes',[]):
            if service=='inbox-worker' and v.get('target')=='/opt/worker-preflight.py' and v.get('source')==str(plan.bundle/'worker_preflight.py'):
                v['source']=str(correction_file(plan))
            key=(v.get('target'),v.get('source'))
            if v.get('type')!='bind' or key not in expected or key in seen:raise Stop('COMPOSE_BINDS')
            v['read_only']=not expected[key];seen.add(key)
        if seen!=set(expected):raise Stop('COMPOSE_BINDS')
        item['tmpfs']=[p+':'+flags for p,flags in tmpfs(service).items()]
        if service=='inbox-worker':
            item['environment'].update(HERMES_RUNTIME_DIR='/worker-home',HERMES_WRITE_SAFE_ROOT='/worker-home',XDG_RUNTIME_DIR='/worker-home')
    return rendered


SELECT = ('.Id','.Image','.Config.Labels','.Config.User','.State.Running','.HostConfig.ReadonlyRootfs',
          '.HostConfig.Privileged','.HostConfig.CapDrop','.HostConfig.SecurityOpt','.HostConfig.PidMode',
          '.HostConfig.IpcMode','.HostConfig.NetworkMode','.HostConfig.PidsLimit','.HostConfig.Memory',
          '.HostConfig.NanoCpus','.HostConfig.RestartPolicy.Name','.HostConfig.Tmpfs','.Mounts',
          '.NetworkSettings.Networks','.NetworkSettings.Ports','.HostConfig.CapAdd','.HostConfig.Devices',
          '.HostConfig.DeviceRequests','.HostConfig.UsernsMode','.HostConfig.CgroupnsMode',
          '.Config.Entrypoint','.Config.Cmd')
FORMAT='\n'.join('{{json '+p+'}}' for p in SELECT)


def confined(data,ident,service,plan,running):
    labels=data['.Config.Labels'] or {}
    if (not re.fullmatch('[0-9a-f]{64}',ident) or data['.Id']!=ident or data['.Image']!=plan.image or
        labels.get('org.signal-desk.issue41.attempt')!=plan.attempt or
        labels.get('com.docker.compose.project')!='signal-desk-bridge-once' or labels.get('com.docker.compose.service')!=service or
        running is not None and data['.State.Running'] is not running):raise Stop('OWNED_IDENTITY')
    proxy=service=='connect-proxy'
    expected={'.Config.User':'65534:65534' if proxy else '10000:10000','.HostConfig.ReadonlyRootfs':True,
        '.HostConfig.Privileged':False,'.HostConfig.CapDrop':['ALL'],'.HostConfig.PidMode':'',
        '.HostConfig.PidsLimit':32 if proxy else 128,'.HostConfig.Memory':134217728 if proxy else 1610612736,
        '.HostConfig.NanoCpus':250000000 if proxy else 1000000000,'.HostConfig.RestartPolicy.Name':'no','.HostConfig.Tmpfs':tmpfs(service),
        '.HostConfig.UsernsMode':'','.Config.Entrypoint':['/opt/hermes/.venv/bin/python'],
        '.Config.Cmd':['-B','/opt/connect-proxy.py'] if proxy else ['-I','-B','-c','import time; time.sleep(7200)']}
    if any(data[k]!=v for k,v in expected.items()):raise Stop('CONFINEMENT')
    names={'signal-desk-bridge-once_worker_isolated'}
    if proxy:names.add('signal-desk-bridge-once_proxy_uplink')
    if (data['.HostConfig.IpcMode'] not in ('','private') or
        data['.HostConfig.CgroupnsMode'] not in ('','private') or
        any(data[k] for k in ('.HostConfig.CapAdd','.HostConfig.Devices','.HostConfig.DeviceRequests')) or
        data['.HostConfig.NetworkMode'] not in names or
        data['.HostConfig.SecurityOpt'] not in (['no-new-privileges'],['no-new-privileges:true']) or
        any(v for v in (data['.NetworkSettings.Ports'] or {}).values())):raise Stop('NAMESPACE_PORTS')
    wanted=mounts(plan,service);observed={}
    for v in data['.Mounts']:
        if v.get('Type')=='tmpfs' and v.get('Destination') in tmpfs(service):continue
        key=(v.get('Destination'),v.get('Source'))
        if v.get('Type')!='bind' or key in observed or v.get('Propagation')!='rprivate':raise Stop('ACTUAL_BINDS')
        observed[key]=v.get('RW')
    if observed!=wanted:raise Stop('ACTUAL_BINDS')
    nets=set(data['.NetworkSettings.Networks'])
    if nets!=names:raise Stop('ACTUAL_NETWORKS')
    return {'Id':ident,'Image':plan.image,'Config':{'Labels':labels},'State':{'Running':data['.State.Running']}}


def configure(ops,config_file):
    def container(ident,service,*,running=None):
        lines=ops._docker('inspect','--type','container','--format',FORMAT,ident,timeout=5).splitlines()
        if len(lines)!=len(SELECT):raise Stop('CONTAINER_INSPECTION')
        result=confined(dict(zip(SELECT,map(json.loads,lines))),ident,service,ops.plan,running)
        env_names=ops._docker('inspect','--type','container','--format',
            '{{range .Config.Env}}{{println (index (split . "=") 0)}}{{end}}',ident,timeout=5).splitlines()
        if env_names and env_names[-1]=='':env_names.pop()
        allowed=IMAGE_ENV|{'GIT_CONFIG_GLOBAL','GIT_CONFIG_NOSYSTEM','TERMINAL_ENV','TMPDIR',
                          'HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY'}
        if len(env_names)!=len(set(env_names)) or not set(env_names).issubset(allowed):raise Stop('ACTUAL_ENVIRONMENT_NAMES')
        if service=='inbox-worker':
            for role,network in ops.network_ids.items():
                records=json.loads(ops._docker('network','inspect',network,timeout=5))
                if len(records)!=1 or records[0].get('Id')!=network:raise Stop('NETWORK_IDENTITY')
                peers=records[0].get('Containers') or {}
                wanted={ops.proxy_id,ident} if role=='worker_isolated' else {ops.proxy_id}
                if set(peers)!=wanted:raise Stop('NETWORK_PEERS')
                if role=='worker_isolated' and (peers[ident].get('IPv4Address')!='172.30.50.2/28' or
                    peers[ops.proxy_id].get('IPv4Address')!='172.30.50.3/28'):raise Stop('NETWORK_ADDRESSES')
        return result
    def compose(*args,timeout=45):
        return ops._call(['docker','compose','--env-file','/dev/null','-f',config_file,'--profile','execution',*args],timeout,env=ops._env())
    ops._container=container;ops._compose=compose


def preflight(ops,host):
    host.require_host_tools();p=ops.plan
    image=ops._docker('image','inspect','--format','{{.Id}}\n{{json .Config.Volumes}}\n{{range .Config.Env}}{{println (index (split . "=") 0)}}{{end}}',p.image).splitlines()
    if image and image[-1]=='':image.pop()
    if len(image)<2 or image[0]!=p.image or not set(json.loads(image[1]) or {}).issubset(set(TMPFS)|{'/worker-home'}) or not set(image[2:]).issubset(IMAGE_ENV):
        raise Stop('IMAGE_METADATA_REVIEW')
    ids=ops._docker('ps','-aq','--no-trunc').splitlines()
    if len(ids)>32 or any(not re.fullmatch('[0-9a-f]{64}',i) for i in ids):raise Stop('CONTAINER_INVENTORY')
    roots=(p.bundle.parent,p.source,p.journal_parent,p.signer_state_root)
    for ident in ids:
        fields='{{json .Image}}\n{{json .HostConfig.Privileged}}\n{{json .HostConfig.PidMode}}\n{{json .Mounts}}'
        rows=ops._docker('inspect','--type','container','--format',fields,ident).splitlines()
        if len(rows)!=4:raise Stop('EXISTING_METADATA')
        image,priv,pid,binds=map(json.loads,rows)
        for bind in binds:
            src=Path(bind.get('Source','/nonexistent'))
            if bind.get('Type')=='bind' and any(src==r or src in r.parents or r in src.parents for r in roots):
                raise Stop('EXISTING_PROTECTED_PATH_EXPOSURE')
            if image==p.image and (priv or pid=='host' or 'docker.sock' in str(src)):
                raise Stop('EXISTING_HERMES_ESCAPE_REVIEW')
    if ops._compose('ps','-q').strip():raise Stop('EXISTING_ATTEMPT')
    if ops._docker('network','ls','-q','--filter','label=com.docker.compose.project=signal-desk-bridge-once').strip():raise Stop('EXISTING_NETWORK')
    rules=ops._call(['iptables','-S'])
    if 'SD_ONCE_IN' in rules or 'SD_ONCE_FWD' in rules:raise Stop('EXISTING_FIREWALL')
    ops._call(['python3','-I','-B',p.bundle/'network_preflight.py'],timeout=35)
    ops.baseline=(ops._docker('ps','-aq','--no-trunc'),ops._docker('network','ls','-q','--no-trunc'))


def device(ops,*,deadline,clock=time.monotonic):
    ops._container(ops.worker_id,'inbox-worker',running=True)
    help_text=ops._worker('hermes','auth','add','--help',timeout=30)
    if not all(flag in help_text for flag in ('--type','--no-browser','--timeout')):raise Stop('DEVICE_CLI_UNSUPPORTED')
    seconds=min(480,deadline-clock())
    if seconds<=0:raise TimeoutError()
    # Device URL/code stay on the operator TTY, never a log/receipt/GitHub post.
    terminal=termios.tcgetattr(0)
    child=subprocess.Popen(['/usr/bin/docker','exec','-it',ops.worker_id,*PROVIDER],
        env={'PATH':'/usr/bin:/bin','HOME':'/nonexistent','DOCKER_CONFIG':'/nonexistent',
             'DOCKER_HOST':'unix:///var/run/docker.sock','LC_ALL':'C'},start_new_session=True)
    try:
        if child.wait(timeout=seconds)!=0:raise Stop('DEVICE_AUTH_FAILED')
    finally:
        try:
            if child.poll() is None:
                os.killpg(child.pid,signal.SIGKILL);child.wait(timeout=3)
        finally:termios.tcsetattr(0,termios.TCSADRAIN,terminal)
        # The flow's finally then stops/removes the exact worker container. A
        # dead Docker client alone is never represented as a stopped OAuth child.


def run(journal,ops,host,*,deadline,authenticate=device,clock=time.monotonic):
    journal.create();owned=();unknown=False;auth=False;github=False;cleaned=False;failure=None
    stage='METADATA_PREFLIGHT';failure_phase=None;owner_code=None;exit_code=None
    effect_deadline=deadline-RESERVE;ops.deadline=effect_deadline
    try:
        journal.record('preflight',intent='preflight');preflight(ops,host)
        rendered=json.loads(ops._compose('config','--format','json'))
        preflight_path=correction_file(ops.plan)
        if preflight_path.parent!=journal.directory:raise Stop('CORRECTION_PATH')
        fd=os.open(preflight_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o444)
        with os.fdopen(fd,'wb') as f:f.write(WORKER_PREFLIGHT_V3);f.flush();os.fsync(f.fileno())
        config=auth_config(rendered,ops.plan)
        config_path=journal.directory/'compose.auth-only.json'
        fd=os.open(config_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as f:json.dump(config,f);f.flush();os.fsync(f.fileno())
        parent=os.open(journal.directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:os.fsync(parent)
        finally:os.close(parent)
        configure(ops,config_path)
        stage='START_ISOLATION'
        journal.record('start_isolation',intent='start_isolation')
        owned=ops.start_isolation()
        if not isinstance(owned,tuple) or len(owned)!=5 or not all(isinstance(x,host.Owned) for x in owned):raise Stop('OWNED_RESOURCES')
        journal.record('start_isolation',intent=None,owned=owned,status='pending')
        stage='OWNER_PREFLIGHT'
        owner=json.loads(ops._worker('/opt/hermes/.venv/bin/python','-I','-B','/opt/worker-preflight.py',timeout=35))
        if owner!={'worker_owner_git':True,'credential_helper_configured':True}:raise Stop('WORKER_OWNER_CONFIG')
        stage='GITHUB_READONLY'
        journal.record('github_reads',intent='github_reads');ops.github_reads();github=True
        journal.record('github_reads',intent=None)
        if clock()>=effect_deadline:raise TimeoutError()
        stage='PROVIDER_DEVICE_LOGIN'
        journal.record('login',intent='login');authenticate(ops,deadline=effect_deadline);auth=True
        journal.record('login',intent=None)
    except (Exception,KeyboardInterrupt) as exc:
        failure=str(exc) if isinstance(exc,Stop) and re.fullmatch('[A-Z0-9_]{1,80}',str(exc)) else 'AUTH_ERROR_'+type(exc).__name__.upper()
        failure_phase=stage
        if isinstance(exc,subprocess.CalledProcessError):
            exit_code=exc.returncode if type(exc.returncode) is int and 0<=exc.returncode<=255 else None
            output=exc.stdout if isinstance(exc.stdout,bytes) else b''
            match=re.fullmatch(rb'WORKER_PREFLIGHT: BLOCKED CODE=([A-Z0-9_]{1,80})\n',output)
            if stage=='OWNER_PREFLIGHT' and match:owner_code=match.group(1).decode('ascii')
        unknown=journal.state['intent']=='start_isolation'
        if unknown:journal.record('blocked',status='blocked',unresolved='start_isolation')
    finally:
        ops.deadline=deadline
        if owned and not unknown:
            try:
                journal.record('cleanup',intent='cleanup')
                if ops.inspect_owned(owned) is not True or ops.cleanup(owned)!=owned or ops.cleanup_readback(owned) is not True:
                    raise Stop('CLEANUP_UNVERIFIED')
                cleaned=True;journal.record('cleanup',intent=None,owned=(),cleanup=True)
            except (Exception,KeyboardInterrupt):
                failure=failure or 'CLEANUP_UNVERIFIED';failure_phase=failure_phase or 'CLEANUP';journal.record('blocked',status='blocked',unresolved='cleanup')
        result={'schema':1,'github_readonly_verified':github,'device_cli_success':auth,'cleanup_verified':cleaned,
                'partial_startup':unknown,'failure':failure,'failure_phase':failure_phase,'worker_preflight_code':owner_code,'child_exit_code':exit_code,'enrollment':False,'signing':False,'dispatch':False,
                'timer':False,'model_entitlement':'UNPROVEN','manager_exclusivity':'UNPROVEN'}
        fd=os.open(journal.directory/'auth-only-receipt.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'w') as f:json.dump(result,f,sort_keys=True);f.flush();os.fsync(f.fileno())
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace',required=True);parser.add_argument('--authenticate',action='store_true')
    args=parser.parse_args()
    previous=signal.getsignal(signal.SIGTERM)
    def interrupted(*_):raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM,interrupted)
    try:
        host,plan=load(args.workspace)
        if not args.authenticate:
            print('AUTH_ONLY: REVIEWED_FILES_ONLY; no host runtime or credential action');return 0
        if not sys.stdin.isatty():raise Stop('LIVE_OPERATOR_TTY_REQUIRED')
        deadline=time.monotonic()+1200
        journal=host.Journal(plan.journal_parent/CORRECTED_JOURNAL,plan.attempt)
        ops=host.HostOperations(plan,runner=host.CommandRunner(deadline=deadline),deadline=deadline)
        result=run(journal,ops,host,deadline=deadline)
        print('GITHUB_READONLY: '+('VERIFIED_WORKER_NAMESPACE' if result['github_readonly_verified'] else 'UNVERIFIED'))
        print('PROVIDER_DEVICE_LOGIN: '+('CLI_REPORTED_SUCCESS' if result['device_cli_success'] else 'UNVERIFIED'))
        print('AUTH_RUNTIME_CLEANUP: '+('EXACT_IDS_VERIFIED' if result['cleanup_verified'] else 'UNVERIFIED_PRESERVE'))
        if result['failure']:print('AUTH_ONLY_FAILURE: '+result['failure'])
        if result['failure_phase']:print('AUTH_ONLY_FAILURE_STAGE: '+result['failure_phase'])
        if result['worker_preflight_code']:print('WORKER_PREFLIGHT_CODE: '+result['worker_preflight_code'])
        print('SIGNING_ENROLLMENT_TIMER_DISPATCH: NOT_STARTED')
        print('OVERALL: NO-GO — authentication is not model entitlement, task authority or installed loop')
        return 0 if result['github_readonly_verified'] and result['device_cli_success'] and result['cleanup_verified'] else 2
    except (Exception,KeyboardInterrupt) as exc:
        code=str(exc) if isinstance(exc,Stop) and re.fullmatch('[A-Z0-9_]{1,80}',str(exc)) else 'PRESERVE_STATE'
        category=type(exc).__name__
        if category not in ('Stop','FileExistsError','FileNotFoundError','PermissionError','ValueError','TypeError',
                            'KeyError','AttributeError','JSONDecodeError','OSError','RuntimeError','TimeoutError','KeyboardInterrupt'):
            category='OTHER'
        site='UNKNOWN';tb=exc.__traceback__
        public={'authenticate_worker_clone_fix.py','operator_host_v2.py','operator_lifecycle.py','root_signer.py'}
        while tb:
            frame=tb.tb_frame.f_code
            if (Path(frame.co_filename).name in public or frame.co_filename.startswith('<reviewed-')) and re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,63}',frame.co_name):
                site=frame.co_name+':'+str(tb.tb_lineno)
            tb=tb.tb_next
        print('STOP: AUTH_ONLY '+code+' TYPE='+category+' SITE='+site+'; preserve files/resources; no retry or guessed cleanup');return 1
    finally:signal.signal(signal.SIGTERM,previous)


if __name__=='__main__':raise SystemExit(main())

