"""Read-only fixed-attempt metadata. Never read credentials or run staging."""
import argparse
import json
import os
from pathlib import Path
import stat

ATTEMPT = 'issue41-cold-20261110-01'
SUFFIXES = ('bootstrap-spec.json','bootstrap.py','bundle','runner','state','auth',
            'context','home','inbox','journal_parent','signer-policy.json',
            'operator-plan.json','staging-receipt.json')


def describe(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return 'ABSENT'
    kind = ('SYMLINK' if stat.S_ISLNK(info.st_mode) else
            'DIRECTORY' if stat.S_ISDIR(info.st_mode) else
            'FILE' if stat.S_ISREG(info.st_mode) else 'OTHER')
    return f'{kind} UID={info.st_uid} GID={info.st_gid} MODE={stat.S_IMODE(info.st_mode):04o}'


def diagnose(workspace_value):
    if os.geteuid() != 0: raise ValueError('root required')
    workspace = Path(workspace_value)
    if (not workspace.is_absolute() or str(workspace) != workspace_value or
            '..' in workspace.parts or workspace == Path('/')): raise ValueError('path')
    for path in (workspace, *workspace.parents):
        info = path.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022 or
                (path == workspace and info.st_mode & 0o077)): raise ValueError('ancestor')
    manifest = workspace/'setup-manifest.json'
    fd = os.open(manifest, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077 or
                not 0 < info.st_size <= 8192): raise ValueError('manifest')
        raw = os.read(fd,8193)
    finally:
        os.close(fd)
    data = json.loads(raw)
    vm = data.get('venv_metadata', {})
    status = vm.get('status')
    print('VENV_STATUS:', status if status in ('READY_METADATA_ONLY','PRIVATE_COPY_REVIEW_REQUIRED','UNPROVEN') else 'INVALID')
    for key in ('uid','gid','mode'):
        value = vm.get(key)
        print('VENV_'+key.upper()+':', value if type(value) is int and 0 <= value <= 2**32 else 'UNKNOWN')
    if isinstance(vm.get('path'), str) and vm['path'].startswith('/'):
        print('VENV_CURRENT:', describe(Path(vm['path'])))
        print('VENV_CONFIG_CURRENT:', describe(Path(vm['path'])/'pyvenv.cfg'))
    print('SIGNER_CLAIM_STATE:', describe(Path('/var/lib/signal-desk/issue41-signer-claims')))
    # No arbitrary input path is opened. Only the public setup manifest above is
    # read; all fixed-attempt paths below are lstat-only, including symlinks.
    for suffix in SUFFIXES:
        print('STAGE_'+suffix.upper().replace('.','_').replace('-','_')+':',
              describe(workspace/(ATTEMPT+'-'+suffix)))
    print('READ_ONLY_COMPLETE: no writes, credential reads, Docker, Git or staging')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', required=True)
    args = parser.parse_args()
    try:
        diagnose(args.workspace)
        return 0
    except Exception:
        print('STOP: METADATA_DIAGNOSTIC_UNVERIFIED; no changes made')
        return 1


if __name__ == '__main__': raise SystemExit(main())
