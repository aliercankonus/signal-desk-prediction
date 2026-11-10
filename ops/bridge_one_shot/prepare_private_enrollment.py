"""Operator-only cold inputs: new root key and two new narrowly scoped tokens.

No provider login, worker credential installation, signer/grant, timer or task.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import resource
import select
import signal
import stat
import subprocess
import termios
import time
import types
import urllib.error
import urllib.parse
import urllib.request

REPO = 'aliercankonus/signal-desk-prediction'
OWNER = 'aliercankonus'
OWNER_ID = 35579049
REPO_ID = 1434992935
PROBE_HEAD = '765c4cbcec1ccbf316679b68bfdba077fd031b33'
TASK_DIGEST = 'c9e4e393ccc506954f0a18e6eaeea7c82ff598b0b41eac642d7f88da1fca73c6'
GUIDE_SHA = 'c1bc75f44a195ac2d34ac8000a983a9bbb6ab74369c212c96d5504f544697f8a'
ENV_NAMES = '{{range .Config.Env}}{{println (index (split . "=") 0)}}{{end}}'
DESTINATIONS = ('private-inputs-intent.json', 'manager-key.pem', 'manager-public.pem',
                'root-github-token', 'worker-github-token', 'private-inputs-receipt.json')
ENV = {'PATH':'/usr/bin:/bin', 'HOME':'/nonexistent', 'LC_ALL':'C'}
READ_PATHS = (
    '/user', '/repos/' + REPO, '/repos/' + REPO + '/issues/43',
    '/repos/' + REPO + '/commits/' + PROBE_HEAD + '/check-runs?per_page=1',
    '/repos/' + REPO + '/actions/runs?head_sha=' + PROBE_HEAD + '&per_page=1',
)


class Stop(Exception):
    pass


def path(value):
    candidate = Path(value)
    if (not value.startswith('/') or value == '/' or str(candidate) != value or
            '..' in candidate.parts or len(value) > 512 or any(ord(c) < 32 for c in value)):
        raise Stop('INVALID_PATH')
    return candidate


def root_directory(folder, private=False):
    for parent in (folder, *folder.parents):
        info = parent.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022 or
                (parent == folder and private and info.st_mode & 0o077)):
            raise Stop('UNTRUSTED_ROOT_DIRECTORY')


def root_bytes(file, limit):
    root_directory(file.parent, private=True)
    before = file.lstat()
    if (not stat.S_ISREG(before.st_mode) or before.st_uid != 0 or
            before.st_mode & 0o077 or not 0 < before.st_size <= limit):
        raise Stop('UNTRUSTED_ROOT_INPUT')
    fd = os.open(file, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino, opened.st_size) != (
                before.st_dev, before.st_ino, before.st_size):
            raise Stop('INPUT_CHANGED')
        data = os.read(fd, limit + 1)
        if len(data) != before.st_size:
            raise Stop('INPUT_CHANGED')
        return data
    finally:
        os.close(fd)


def image_env_names(raw):
    names = raw.decode('ascii').splitlines()
    # println emits one LF per name; docker inspect --format appends a final
    # LF as well. Discard only that single empty terminal record. Interior
    # empty names and additional malformed records still fail validation.
    if names and names[-1] == '':
        names.pop()
    if len(names) > 256 or any(not re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,127}', name) or
            re.search('TOKEN|SECRET|KEY|PASSWORD|CREDENTIAL|AUTH', name, re.I) for name in names):
        raise Stop('IMAGE_ENV_NAMES_REQUIRE_REVIEW')
    return names


def preflight(workspace, image):
    root_directory(workspace, private=True)
    if not re.fullmatch('sha256:[0-9a-f]{64}', image):
        raise Stop('IMMUTABLE_IMAGE_REQUIRED')
    for name in DESTINATIONS:
        if os.path.lexists(workspace / name):
            raise Stop('COLD_INPUT_OR_INTENT_EXISTS_PRESERVE_STATE')
    record = json.loads(root_bytes(workspace / 'setup-manifest.json', 8192))
    if (not isinstance(record, dict) or type(record.get('schema')) is not int or
            record.get('schema') != 1 or record.get('purpose') != 'public-setup-workspace-only' or
            record.get('workspace') != str(workspace) or record.get('runtime_authority') is not False or
            record.get('credential_provisioning') is not False or
            record.get('source_pin') != '0fbf46053a74bad4a35ecb3d324b6decab530b83' or
            record.get('files') != {'prepare_operator_spec.py':GUIDE_SHA,
              'install_operator_bootstrap.sh':'ee29f7b42e36b79ca46e8516e0fa3b0a321b481b2c244edf4970f81564da638d'}):
        raise Stop('WORKSPACE_MANIFEST_MISMATCH')
    venv = record.get('venv_metadata')
    if (not isinstance(venv, dict) or set(venv) - {'path','status','uid','gid','mode'} or
            not isinstance(venv.get('path'), str) or venv.get('status') not in
            ('READY_METADATA_ONLY','PRIVATE_COPY_REVIEW_REQUIRED','UNPROVEN')):
        raise Stop('WORKSPACE_MANIFEST_MISMATCH')
    source = path(record['source'])
    root_directory(source, private=True)
    guide_bytes = root_bytes(workspace / 'prepare_operator_spec.py', 32768)
    if hashlib.sha256(guide_bytes).hexdigest() != GUIDE_SHA:
        raise Stop('GUIDE_DIGEST_MISMATCH')
    guide = types.ModuleType('reviewed_private_input_guide')
    exec(compile(guide_bytes, '<reviewed-private-input-guide>', 'exec'), guide.__dict__)
    boot = guide.load_consumer(str(source))
    boot.STAGING_DEADLINE = time.monotonic() + 180
    if boot.command(['docker','image','inspect','--format','{{.Id}}',image]).strip() != image.encode():
        raise Stop('IMAGE_ID_MISMATCH')
    # The Docker template emits variable NAMES only, never values. This check
    # is not image-filesystem/credential/App isolation proof.
    image_env_names(boot.command(['docker','image','inspect','--format',ENV_NAMES,image]))
    ids = boot.command(['docker','ps','-aq','--no-trunc']).decode('ascii').splitlines()
    if len(ids) > 32 or len(set(ids)) != len(ids) or any(not re.fullmatch('[0-9a-f]{64}', i) for i in ids):
        raise Stop('DOCKER_INVENTORY_BOUND')
    for ident in ids:
        mounts = json.loads(boot.command(['docker','inspect','--type','container','--format','{{json .Mounts}}',ident]))
        if not isinstance(mounts, list) or len(mounts) > 64:
            raise Stop('DOCKER_MOUNTS_INVALID')
        for mount in mounts:
            if not isinstance(mount, dict) or mount.get('Type') not in ('bind','volume','tmpfs'):
                raise Stop('DOCKER_MOUNTS_INVALID')
            path(mount.get('Destination', ''))
            if mount['Type'] == 'tmpfs':
                if mount.get('Source') not in ('', 'tmpfs'):
                    raise Stop('DOCKER_MOUNTS_INVALID')
                continue
            origin = path(mount.get('Source', ''))
            if any(boot._overlap(origin, target) for target in (source, workspace)):
                raise Stop('CURRENT_MOUNT_OVERLAP')
    return record


def check_system():
    program = Path('/usr/bin/openssl')
    root_directory(program.parent)
    info = program.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022 or not info.st_mode & 0o111:
        raise Stop('TRUSTED_SYSTEM_OPENSSL_REQUIRED')


def secret_input(label, deadline):
    # Unbuffered binary update mode supports non-seekable terminals. Text r+
    # requests a seekable buffered pair and fails on a real Linux TTY.
    with open('/dev/tty', 'r+b', buffering=0) as tty:
        if not tty.isatty():
            raise Stop('PRIVATE_OPERATOR_TTY_REQUIRED')
        before = termios.tcgetattr(tty.fileno())
        hidden = before[:]
        hidden[3] &= ~termios.ECHO
        try:
            termios.tcsetattr(tty.fileno(), termios.TCSAFLUSH, hidden)
            tty.write((label + ': ').encode('ascii'))
            tty.flush()
            remaining = min(600, deadline - time.monotonic())
            if remaining <= 0 or not select.select([tty], [], [], remaining)[0]:
                raise Stop('PRIVATE_INPUT_TIMEOUT')
            value = tty.readline(513)
            if not value.endswith(b'\n') or len(value) > 512:
                raise Stop('PRIVATE_INPUT_BOUND')
            return value.rstrip(b'\r\n').decode('ascii')
        finally:
            termios.tcsetattr(tty.fileno(), termios.TCSAFLUSH, before)
            tty.write(b'\n')
            tty.flush()


def token_template(role):
    permissions = {'contents':'read', 'issues':'write', 'pull_requests':'read',
                   'actions':'read', 'statuses':'read'}
    if role == 'worker':
        permissions.update(contents='write', pull_requests='write')
    elif role != 'root':
        raise Stop('UNKNOWN_TOKEN_ROLE')
    return 'https://github.com/settings/personal-access-tokens/new?' + urllib.parse.urlencode({
        'name':'Signal Desk ' + role, 'target_name':OWNER, 'expires_in':30, **permissions})


def github_get(token, route, deadline):
    if route not in READ_PATHS or (token is None and route != '/repos/' + REPO + '/issues/43'):
        raise Stop('READ_ROUTE_OUTSIDE_SCOPE')
    headers = {'Accept':'application/vnd.github+json', 'X-GitHub-Api-Version':'2022-11-28',
               'User-Agent':'signal-desk-cold-private-inputs'}
    if token is not None:
        headers['Authorization'] = 'Bearer ' + token
    request = urllib.request.Request('https://api.github.com' + route, headers=headers, method='GET')
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            raise Stop('GITHUB_REDIRECT_DENIED')
    remaining = min(12, deadline - time.monotonic())
    if remaining <= 0 or signal.getitimer(signal.ITIMER_REAL)[0]:
        raise Stop('READ_DEADLINE_OR_EXISTING_TIMER')
    before = signal.getsignal(signal.SIGALRM)
    def timeout(*_):
        raise TimeoutError()
    signal.signal(signal.SIGALRM, timeout)
    signal.setitimer(signal.ITIMER_REAL, remaining)
    try:
        try:
            with urllib.request.build_opener(NoRedirect).open(request, timeout=remaining) as response:
                raw = response.read(65537)
                if len(raw) > 65536:
                    raise Stop('GITHUB_RESPONSE_BOUND')
                return json.loads(raw)
        except urllib.error.HTTPError as exc:
            raise Stop('GITHUB_HTTP_' + str(exc.code)) from None
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, before)


def verify_reads(token, get, deadline):
    if not isinstance(token, str) or not re.fullmatch('github_pat_[A-Za-z0-9_]{32,500}', token):
        raise Stop('NEW_FINE_GRAINED_TOKEN_REQUIRED')
    user = get(token, '/user', deadline)
    if not isinstance(user, dict) or user.get('id') != OWNER_ID or user.get('login') != OWNER:
        raise Stop('GITHUB_IDENTITY_MISMATCH')
    repo = get(token, '/repos/' + REPO, deadline)
    if not isinstance(repo, dict) or repo.get('id') != REPO_ID or repo.get('full_name') != REPO:
        raise Stop('GITHUB_REPOSITORY_MISMATCH')
    checks = get(token, READ_PATHS[3], deadline)
    actions = get(token, READ_PATHS[4], deadline)
    if (not isinstance(checks, dict) or not isinstance(checks.get('check_runs'), list) or
            not isinstance(actions, dict) or not isinstance(actions.get('workflow_runs'), list)):
        raise Stop('GITHUB_READ_RESPONSE_INVALID')
    # These are host-side authenticated GETs, not proof of write scopes, actual
    # worker access, or a new task's exact-head CI. Public reads cannot prove scope.


def make_keypair():
    def openssl(args, data=None):
        result = subprocess.run(['/usr/bin/openssl', *args], input=data,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=ENV, timeout=10, check=True)
        if not 0 < len(result.stdout) <= 8192:
            raise Stop('NEW_KEY_OUTPUT_BOUND')
        return result.stdout
    private = openssl(('genpkey','-algorithm','ED25519'))
    public = openssl(('pkey','-pubout'), private)
    if (not private.startswith(b'-----BEGIN PRIVATE KEY-----\n') or
            not public.startswith(b'-----BEGIN PUBLIC KEY-----\n')):
        raise Stop('NEW_KEY_FORMAT_INVALID')
    return private, public


def publish(folder, name, data):
    if name not in DESTINATIONS:
        raise Stop('PUBLICATION_OUTSIDE_SCOPE')
    if isinstance(data, dict):
        data = json.dumps(data, sort_keys=True, separators=(',', ':')).encode() + b'\n'
    if not isinstance(data, bytes) or not 0 < len(data) <= 8192:
        raise Stop('PRIVATE_PUBLICATION_BOUND')
    parent = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600, dir_fd=parent)
        with os.fdopen(fd, 'wb') as output:
            os.fchown(output.fileno(), 0, 0)
            output.write(data)
            os.fsync(output.fileno())
        os.fsync(parent)
    finally:
        os.close(parent)


def prepare(workspace_value, image, *, provision=False, prompt=secret_input,
            get=github_get, keypair=make_keypair, system_check=check_system):
    if os.geteuid() != 0:
        raise Stop('ROOT_REQUIRED')
    workspace = path(workspace_value)
    record = preflight(workspace, image)
    system_check()
    deadline = time.monotonic() + 1800
    task = get(None, '/repos/' + REPO + '/issues/43', deadline)
    if (not isinstance(task, dict) or task.get('number') != 43 or task.get('state') != 'open' or
            not isinstance(task.get('body'), str) or
            hashlib.sha256(task['body'].encode()).hexdigest() != TASK_DIGEST):
        raise Stop('FROZEN_TASK_CHANGED')
    if not provision:
        print('COLD_INPUT_PLAN: READY; no secret prompts, keys or files created')
        print('OVERALL: NO-GO — cold preparation only')
        return
    tokens = {}
    for role in ('root','worker'):
        print('Create a DISTINCT NEW ' + role + ' token; keep its browser tab open until completion.', flush=True)
        print('Select ONLY repository ' + REPO + '; inspect permissions; no administration/workflows/secrets.', flush=True)
        print(token_template(role), flush=True)
        token = prompt('Paste NEW ' + role + ' fine-grained token here (hidden; never in chat)', deadline)
        verify_reads(token, get, deadline)
        tokens[role] = token
    if hmac.compare_digest(tokens['root'], tokens['worker']):
        raise Stop('DISTINCT_ROOT_AND_WORKER_TOKENS_REQUIRED')
    private, public = keypair()
    if not 0 < len(private) <= 8192 or not 0 < len(public) <= 8192 or deadline - time.monotonic() < 30:
        raise Stop('PRIVATE_INPUT_BUDGET_OR_SIZE')
    # Recheck publication targets immediately before the intent. No overwrites,
    # rollback, remote write, signature or retry, including after interruption.
    root_directory(workspace, private=True)
    if any(os.path.lexists(workspace / name) for name in DESTINATIONS):
        raise Stop('COLD_INPUT_OR_INTENT_EXISTS_PRESERVE_STATE')
    intent = {'schema':1, 'purpose':'unused-cold-inputs-only',
              'created_at':datetime.now(timezone.utc).isoformat(), 'activation':False}
    publish(workspace, DESTINATIONS[0], intent)
    publish(workspace, 'manager-key.pem', private)
    publish(workspace, 'manager-public.pem', public)
    publish(workspace, 'root-github-token', tokens['root'].encode('ascii'))
    publish(workspace, 'worker-github-token', tokens['worker'].encode('ascii'))
    receipt = {
        **intent, 'repo':REPO, 'owner_id':OWNER_ID, 'image':image,
        'public_key_sha256':hashlib.sha256(public).hexdigest(),
        'source':record['source'], 'venv_metadata':record.get('venv_metadata', {}),
        'read_probe_head':PROBE_HEAD, 'read_evidence':'authenticated GETs on host only',
        'write_scope_evidence':'operator-declared; not established by public GETs',
        'requested_expiration_days':30, 'observed_expiration':'UNPROVEN',
        'worker_credentials_installed':False, 'manager_app_exclusivity':'UNPROVEN',
        'provider_authentication':False, 'task_authority':False,
    }
    publish(workspace, 'private-inputs-receipt.json', receipt)
    print('MANAGER_KEYPAIR: COLD_STORED_ROOT_ONLY')
    print('ROOT_GITHUB_READS: VERIFIED_HOST_ONLY')
    print('WORKER_TOKEN_READS: VERIFIED_HOST_ONLY')
    print('PRIVATE_INPUTS: COLD_READY; worker/provider enrollment not installed')
    print('OVERALL: NO-GO — no signer, service or task activated')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--image', required=True)
    parser.add_argument('--provision', action='store_true')
    args = parser.parse_args()
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    previous = signal.getsignal(signal.SIGTERM)
    def interrupted(*_):
        raise InterruptedError()
    signal.signal(signal.SIGTERM, interrupted)
    try:
        prepare(args.workspace, args.image, provision=args.provision)
    except Stop as exc:
        print('STOP: ' + str(exc))
        print('STATE: preserve any intent/files; no automatic retry or cleanup')
        return 1
    except (Exception, KeyboardInterrupt):
        print('STOP: UNVERIFIED_PRIVATE_INPUT_STATE; preserve files; no retry')
        return 1
    finally:
        signal.signal(signal.SIGTERM, previous)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
