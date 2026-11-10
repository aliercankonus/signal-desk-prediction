"""Operator-only derived spec and staging. No login, signing, services or dispatch."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import time
import types
import urllib.request

REPO = 'aliercankonus/signal-desk-prediction'
PUBLIC = {
    'prepare_private_enrollment.py':'6a80cce4eb9510103f77678be78e57b535b6c4f00852078d191683009e9f2b78',
    'operator_bootstrap_v2.py':'bd224f9ddf7f2985ae11659e2cac13d33b47403ab24bded1e2cef37de4017ac3',
}
GUIDE_SHA = 'c1bc75f44a195ac2d34ac8000a983a9bbb6ab74369c212c96d5504f544697f8a'
REQUIREMENTS = '58f90369318da1e7ab651447080f06bb80c361a4a0109d79eca4762aba8bf97d'
ATTEMPT = 'issue41-cold-20261110-01'


class Stop(Exception): pass


def fetch_public(commit, name):
    if not re.fullmatch('[0-9a-f]{40}', commit) or name not in PUBLIC:
        raise Stop('INVALID_PUBLIC_SOURCE')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs): raise Stop('PUBLIC_REDIRECT')
    if signal.getitimer(signal.ITIMER_REAL)[0]: raise Stop('EXISTING_TIMER')
    def timeout(*_): raise TimeoutError()
    previous = signal.signal(signal.SIGALRM, timeout)
    signal.setitimer(signal.ITIMER_REAL, 20)
    try:
        url = 'https://raw.githubusercontent.com/' + REPO + '/' + commit + '/ops/bridge_one_shot/' + name
        with urllib.request.build_opener(NoRedirect).open(url, timeout=15) as response:
            blob = response.read(32769)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
    if len(blob) > 32768 or hashlib.sha256(blob).hexdigest() != PUBLIC[name]:
        raise Stop('PUBLIC_SOURCE_DIGEST')
    return blob


def module(blob, name):
    result = types.ModuleType(name)
    exec(compile(blob, '<reviewed-' + name + '>', 'exec'), result.__dict__)
    return result


def prepare(workspace_value, commit, cursors, *, stage=False, getter=fetch_public):
    if os.geteuid() != 0: raise Stop('ROOT_REQUIRED')
    # Getter injection exists for offline tests only; CLI has no override.
    blobs = {name:getter(commit, name) for name in PUBLIC}
    for name, blob in blobs.items():
        if len(blob) > 32768 or hashlib.sha256(blob).hexdigest() != PUBLIC[name]:
            raise Stop('PUBLIC_SOURCE_DIGEST')
    cold = module(blobs['prepare_private_enrollment.py'], 'cold_input_policy')
    boot = module(blobs['operator_bootstrap_v2.py'], 'staging_v2')
    workspace = cold.path(workspace_value)
    cold.root_directory(workspace, private=True)
    if (set(cursors) != {'41','45'} or any(type(x) is not int or x < 0 for x in cursors.values())):
        raise Stop('INVALID_CURSORS')
    setup = json.loads(cold.root_bytes(workspace / 'setup-manifest.json', 8192))
    receipt = json.loads(cold.root_bytes(workspace / 'private-inputs-receipt.json', 8192))
    intent = json.loads(cold.root_bytes(workspace / 'private-inputs-intent.json', 8192))
    if (setup.get('schema') != 1 or setup.get('purpose') != 'public-setup-workspace-only' or
            setup.get('workspace') != str(workspace) or setup.get('runtime_authority') is not False or
            setup.get('credential_provisioning') is not False or
            setup.get('source_pin') != '0fbf46053a74bad4a35ecb3d324b6decab530b83' or
            setup.get('files', {}).get('prepare_operator_spec.py') != GUIDE_SHA or
            receipt.get('schema') != 1 or receipt.get('purpose') != 'unused-cold-inputs-only' or
            receipt.get('activation') is not False or receipt.get('task_authority') is not False or
            receipt.get('worker_credentials_installed') is not False or
            receipt.get('provider_authentication') is not False or receipt.get('repo') != REPO or
            receipt.get('owner_id') != 35579049 or receipt.get('source') != setup.get('source') or
            receipt.get('venv_metadata') != setup.get('venv_metadata') or
            intent != {k:receipt[k] for k in ('schema','purpose','created_at','activation')}):
        raise Stop('COLD_RECEIPT_MISMATCH')
    metadata = setup.get('venv_metadata', {})
    if (metadata.get('status') != 'READY_METADATA_ONLY' or metadata.get('uid') != 10000 or
            metadata.get('gid') != 10000 or type(metadata.get('mode')) is not int or
            metadata['mode'] & 0o077):
        raise Stop('ACCEPTED_PRIVATE_VENV_METADATA_REQUIRED')
    venv = cold.path(metadata['path'])
    if venv.parts[-3:] != ('signal-desk-tooling','venvs','issue26-recovery-python314-20261030'):
        raise Stop('REVIEWED_VENV_LAYOUT_REQUIRED')
    # All credential inputs are metadata-only. Only public verifier bytes are read.
    for name in ('manager-key.pem','manager-public.pem','root-github-token','worker-github-token'):
        boot._regular(workspace / name, 0)
    public = cold.root_bytes(workspace / 'manager-public.pem', 8192)
    if (not public.startswith(b'-----BEGIN PUBLIC KEY-----\n') or
            hashlib.sha256(public).hexdigest() != receipt.get('public_key_sha256')):
        raise Stop('PUBLIC_VERIFIER_MISMATCH')
    guide_blob = cold.root_bytes(workspace / 'prepare_operator_spec.py', 32768)
    if hashlib.sha256(guide_blob).hexdigest() != GUIDE_SHA: raise Stop('GUIDE_DIGEST')
    guide = module(guide_blob, 'frozen_spec_guide')
    targets = {key:workspace / (ATTEMPT + suffix) for key, suffix in
               (('spec','-bootstrap-spec.json'),('bootstrap','-bootstrap.py'),('receipt','-staging-receipt.json'))}
    if any(os.path.lexists(p) for p in targets.values()): raise Stop('EXISTING_PREPARATION_PRESERVE')
    values = dict(attempt=ATTEMPT, source=setup['source'], fresh_parent=str(workspace),
        private_parent=str(workspace), venv=str(venv), image=receipt['image'], uid=10000, gid=10000,
        signer_key=str(workspace/'manager-key.pem'), signer_public=str(workspace/'manager-public.pem'),
        signer_token=str(workspace/'root-github-token'), excluded_roots=[str(venv.parents[2])],
        requirements_sha256=REQUIREMENTS, python_version='3.14.9', pytest_version='8.3.3',
        git_name='Signal Desk Worker', git_email='35579049+aliercankonus@users.noreply.github.com',
        cursors=cursors)
    # Frozen guide uses the exact old consumer for schema/metadata admission;
    # separately versioned v2 differs only in its names-only image inspection.
    boot.STAGING_DEADLINE = time.monotonic() + 180
    try:
        cfg = guide.prepare_spec(values, command=boot.command)
    finally:
        boot.STAGING_DEADLINE = None
    if not stage:
        print('DERIVED_SPEC: PREVIEW_READY; no files written')
        print('OVERALL: NO-GO — staging and execution not performed')
        return
    # Spec is also the durable before-effect intent. Any partial state is kept.
    guide.write_spec(targets['spec'], cfg, command=boot.command)
    boot._write(targets['bootstrap'], blobs['operator_bootstrap_v2.py'], 0, 0)
    result = boot.stage(cfg)
    boot._write(targets['receipt'], {'schema':1, 'attempt':ATTEMPT,
        'source_commit':commit, 'bootstrap_sha256':PUBLIC['operator_bootstrap_v2.py'],
        'runner_pin':boot.RUNNER_PIN, 'adapter_pin':boot.MERGE,
        'spec':str(targets['spec']), 'plan':cfg['plan'],
        'activation':False, 'worker_credentials_installed':False,
        'manager_exclusive_invocation':'UNPROVEN',
        'runtime_versions':'historical declarations; not executed by this step',
        'result':result}, 0, 0)
    print('DERIVED_SPEC: WRITTEN_ROOT_ONLY')
    print('STAGING: COMPLETE_NO_ACTIVATION')
    print('WORKER_CREDENTIALS: NOT_INSTALLED')
    print('PROVIDER_AUTH: NOT_STARTED')
    print('OVERALL: NO-GO — manager-exclusive invocation and runtime remain UNPROVEN')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--cursor41', type=int, required=True)
    parser.add_argument('--cursor45', type=int, required=True)
    parser.add_argument('--stage', action='store_true')
    args = parser.parse_args()
    previous = signal.getsignal(signal.SIGTERM)
    def interrupted(*_): raise InterruptedError()
    signal.signal(signal.SIGTERM, interrupted)
    try:
        prepare(args.workspace, args.source_commit, {'41':args.cursor41,'45':args.cursor45}, stage=args.stage)
        return 0
    except (Exception, KeyboardInterrupt):
        print('STOP: STAGING_UNVERIFIED; preserve spec/files; no retry or cleanup')
        return 1
    finally:
        signal.signal(signal.SIGTERM, previous)


if __name__ == '__main__': raise SystemExit(main())
