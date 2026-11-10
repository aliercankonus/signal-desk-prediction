"""Operator-only finish of the verified incomplete #64 preparation clone."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import types
import urllib.request

ATTEMPT = 'issue41-cold-20261110-01'
REPO = 'aliercankonus/signal-desk-prediction'
PUBLIC = {
    'prepare_private_enrollment.py':'6a80cce4eb9510103f77678be78e57b535b6c4f00852078d191683009e9f2b78',
    'operator_bootstrap_v4.py':'459fc5db380f2f25f9db56cb3430712ab738fed2758f3d45482b664e08cfca9d',
}
OLD_BOOTSTRAP = 'bd224f9ddf7f2985ae11659e2cac13d33b47403ab24bded1e2cef37de4017ac3'


class Stop(Exception): pass


def fetch(commit, name):
    if not re.fullmatch('[0-9a-f]{40}', commit) or name not in PUBLIC: raise Stop('SOURCE_INPUT')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs): raise Stop('SOURCE_REDIRECT')
    if signal.getitimer(signal.ITIMER_REAL)[0]: raise Stop('EXISTING_TIMER')
    def timeout(*_): raise TimeoutError()
    previous = signal.signal(signal.SIGALRM, timeout); signal.alarm(20)
    try:
        url = 'https://raw.githubusercontent.com/'+REPO+'/'+commit+'/ops/bridge_one_shot/'+name
        with urllib.request.build_opener(NoRedirect).open(url, timeout=15) as response:
            blob = response.read(65537)
    finally:
        signal.alarm(0); signal.signal(signal.SIGALRM, previous)
    return blob


def load_public(commit, name, getter):
    blob = getter(commit, name)
    if len(blob) > 65536 or hashlib.sha256(blob).hexdigest() != PUBLIC[name]: raise Stop('SOURCE_DIGEST')
    module = types.ModuleType(name[:-3])
    exec(compile(blob, '<reviewed-'+name+'>', 'exec'), module.__dict__)
    return module


def complete(workspace_value, commit, *, apply=False, getter=fetch):
    if os.geteuid() != 0: raise Stop('ROOT_REQUIRED')
    cold = load_public(commit, 'prepare_private_enrollment.py', getter)
    boot = load_public(commit, 'operator_bootstrap_v4.py', getter)
    workspace = cold.path(workspace_value); cold.root_directory(workspace, private=True)
    read_json = lambda name:json.loads(cold.root_bytes(workspace/name,16384))
    setup = read_json('setup-manifest.json')
    receipt = read_json('private-inputs-receipt.json')
    intent = read_json('private-inputs-intent.json')
    if (setup.get('purpose') != 'public-setup-workspace-only' or setup.get('schema') != 1 or
            setup.get('workspace') != str(workspace) or setup.get('runtime_authority') is not False or
            setup.get('credential_provisioning') is not False or
            receipt.get('schema') != 1 or receipt.get('purpose') != 'unused-cold-inputs-only' or
            receipt.get('repo') != REPO or receipt.get('owner_id') != 35579049 or
            receipt.get('activation') is not False or receipt.get('task_authority') is not False or
            receipt.get('worker_credentials_installed') is not False or receipt.get('provider_authentication') is not False or
            receipt.get('source') != setup.get('source') or receipt.get('venv_metadata') != setup.get('venv_metadata') or
            intent != {k:receipt[k] for k in ('schema','purpose','created_at','activation')}):
        raise Stop('COLD_RECEIPT_MISMATCH')
    vm = setup.get('venv_metadata', {})
    if vm.get('status') != 'READY_METADATA_ONLY' or vm.get('uid') != 10000 or vm.get('gid') != 10000:
        raise Stop('REPORTED_VENV_METADATA_MISMATCH')
    raw_spec = cold.root_bytes(workspace/(ATTEMPT+'-bootstrap-spec.json'),16384)
    cfg = json.loads(raw_spec)
    old_bootstrap = cold.root_bytes(workspace/(ATTEMPT+'-bootstrap.py'),32768)
    if hashlib.sha256(old_bootstrap).hexdigest() != OLD_BOOTSTRAP: raise Stop('ORIGINAL_BOOTSTRAP_MISMATCH')
    expected = dict(attempt=ATTEMPT, source=setup['source'], venv=vm['path'], image=receipt['image'],
        uid=10000, gid=10000, signer_key=str(workspace/'manager-key.pem'),
        signer_public=str(workspace/'manager-public.pem'), signer_token=str(workspace/'root-github-token'),
        signer_policy=str(workspace/(ATTEMPT+'-signer-policy.json')),
        plan=str(workspace/(ATTEMPT+'-operator-plan.json')), signer_state_root=boot.SIGNER_STATE,
        merge='eac843de7967d48cce56ee9a198750e98754a2de', overall_seconds=1800,
        task_body_sha256='c9e4e393ccc506954f0a18e6eaeea7c82ff598b0b41eac642d7f88da1fca73c6',
        requirements_sha256='58f90369318da1e7ab651447080f06bb80c361a4a0109d79eca4762aba8bf97d',
        python_version='3.14.9', pytest_version='8.3.3',
        test_python='/opt/data/signal-desk-tooling/venvs/issue26-recovery-python314-20261030/bin/python',
        git_name='Signal Desk Worker', git_email='35579049+aliercankonus@users.noreply.github.com',
        cursors={'41':6761280723,'45':6713729283}, excluded_roots=[str(Path(vm['path']).parents[2])])
    expected.update({key:str(workspace/(ATTEMPT+'-'+key)) for key in boot.PREFIX_KEYS})
    if any(cfg.get(key) != value for key,value in expected.items()): raise Stop('ORIGINAL_SPEC_SCOPE_MISMATCH')
    for name in ('manager-key.pem','manager-public.pem','root-github-token','worker-github-token'):
        boot._regular(workspace/name,0)  # metadata only; never open credentials
    public = cold.root_bytes(workspace/'manager-public.pem',8192)
    if hashlib.sha256(public).hexdigest() != receipt.get('public_key_sha256'): raise Stop('PUBLIC_KEY_MISMATCH')
    result_path = workspace/(ATTEMPT+'-staging-receipt.json')
    if os.path.lexists(result_path): raise Stop('STAGING_RECEIPT_EXISTS')
    boot.validate_spec(cfg, cloned_checkpoint=True)
    if not apply:
        print('CLONE_CHECKPOINT: VERIFIED_READ_ONLY; no changes made')
        print('OVERALL: NO-GO — completion not invoked')
        return
    result = boot.stage(cfg, cloned_checkpoint=True)
    boot._write(result_path, {'schema':1,'attempt':ATTEMPT,'source_commit':commit,
        'original_spec_sha256':hashlib.sha256(raw_spec).hexdigest(),
        'preserved_bootstrap_sha256':OLD_BOOTSTRAP,'completion_engine_sha256':PUBLIC['operator_bootstrap_v4.py'],
        'runner_pin':boot.RUNNER_PIN,'adapter_pin':boot.MERGE,'activation':False,
        'worker_credentials_installed':False,'manager_exclusive_invocation':'UNPROVEN',
        'original_spec_start':cfg['start'],'result':result},0,0)
    print('CLONED_STAGING: COMPLETE_NO_ACTIVATION')
    print('ORIGINAL_SPEC_BOOTSTRAP: PRESERVED')
    print('WORKER_CREDENTIALS: NOT_INSTALLED')
    print('PROVIDER_AUTH: NOT_STARTED')
    print('OVERALL: NO-GO — manager-exclusive invocation and runtime remain UNPROVEN')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace',required=True);parser.add_argument('--source-commit',required=True)
    parser.add_argument('--complete',action='store_true');args=parser.parse_args()
    previous=signal.getsignal(signal.SIGTERM)
    def interrupted(*_): raise InterruptedError()
    signal.signal(signal.SIGTERM,interrupted)
    try:
        complete(args.workspace,args.source_commit,apply=args.complete)
        return 0
    except (Exception,KeyboardInterrupt) as exc:
        category=type(exc).__name__
        if category not in ('Stop','ValueError','PermissionError','FileNotFoundError','FileExistsError',
                            'TimeoutError','RuntimeError','OSError','InterruptedError','KeyError','TypeError','KeyboardInterrupt'):
            category='OTHER'
        site='UNKNOWN';tb=exc.__traceback__
        while tb:
            code=tb.tb_frame.f_code
            if code.co_filename.startswith('<reviewed-') and re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,63}',code.co_name):
                site=code.co_name+':'+str(tb.tb_lineno)
            tb=tb.tb_next
        reason=str(exc) if isinstance(exc,Stop) and re.fullmatch('[A-Z0-9_]{1,80}',str(exc)) else 'PRESERVE_STATE'
        print('STOP: CLONED_STAGING_UNVERIFIED TYPE='+category+' SITE='+site+' CODE='+reason)
        return 1
    finally:
        signal.signal(signal.SIGTERM,previous)


if __name__=='__main__': raise SystemExit(main())
