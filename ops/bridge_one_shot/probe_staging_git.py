"""Read-only Git object/ref probe for the preserved #41 staging runner."""
import argparse
import json
import os
from pathlib import Path
import stat
import subprocess

ATTEMPT='issue41-cold-20261110-01'
PIN='e84021a786004456a12de9e25eae50d191da6cf1'
ENV={'PATH':'/usr/bin:/bin','HOME':'/nonexistent','LC_ALL':'C',
     'GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':'/dev/null',
     'GIT_TERMINAL_PROMPT':'0','GCM_INTERACTIVE':'never'}


def trusted(folder,private=False):
    for path in (folder,*folder.parents):
        info=path.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid!=0 or info.st_mode & 0o022 or
                (private and path==folder and info.st_mode & 0o077)):raise ValueError('untrusted metadata')


def read_manifest(workspace):
    trusted(workspace,True)
    fd=os.open(workspace/'setup-manifest.json',os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=0 or info.st_mode & 0o077 or not 0<info.st_size<=8192:
            raise ValueError('manifest metadata')
        return json.loads(os.read(fd,8193))
    finally:os.close(fd)


def git_read(argv):
    # No user command, remote operation, status/fsmonitor, hook or file-content read.
    result=subprocess.run(['git',*argv],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL,env=ENV,timeout=10,check=False)
    if len(result.stdout)>8192:raise ValueError('git output bound')
    return result.returncode,result.stdout.strip()


def inspect_objects(source,runner,pin=PIN):
    results={}
    code,value=git_read(['--git-dir='+str(source),'cat-file','-t',pin])
    results['SOURCE_CANDIDATE']='PRESENT_COMMIT' if code==0 and value==b'commit' else 'MISSING_OR_UNVERIFIED'
    code,value=git_read(['--git-dir='+str(source),'for-each-ref','--count=1','--format=%(refname)'])
    results['SOURCE_REFS']='NONE' if code==0 and not value else 'PRESENT_OR_UNVERIFIED'
    if not (runner/'.git').is_dir() or (runner/'.git').is_symlink():
        results['RUNNER_GIT']='ABSENT_OR_UNVERIFIED'
        return results
    results['RUNNER_GIT']='DIRECTORY'
    with os.scandir(runner) as entries:
        results['RUNNER_TREE']='ONLY_GIT_DIRECTORY' if all(x.name=='.git' for x in entries) else 'OTHER_ENTRIES_PRESERVE'
    code,value=git_read(['-C',str(runner),'cat-file','-t',pin])
    results['RUNNER_CANDIDATE']='PRESENT_COMMIT' if code==0 and value==b'commit' else 'MISSING_OR_UNVERIFIED'
    code,value=git_read(['-C',str(runner),'rev-parse','--verify','HEAD'])
    results['RUNNER_HEAD']=('CANDIDATE' if code==0 and value==pin.encode() else
                            'OTHER_COMMIT_PRESERVE' if code==0 else 'NO_RESOLVED_COMMIT')
    code,value=git_read(['-C',str(runner),'for-each-ref','--count=1','--format=%(refname)'])
    results['RUNNER_REFS']='NONE' if code==0 and not value else 'PRESENT_OR_UNVERIFIED'
    results['RUNNER_FETCH_HEAD']='PRESENT_PRESERVE' if os.path.lexists(runner/'.git/FETCH_HEAD') else 'ABSENT'
    return results


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--workspace',required=True)
    args=parser.parse_args()
    try:
        if os.geteuid()!=0:raise ValueError('root required')
        workspace=Path(args.workspace)
        if str(workspace)!=args.workspace or not workspace.is_absolute() or '..' in workspace.parts or workspace==Path('/'):
            raise ValueError('workspace')
        manifest=read_manifest(workspace)
        if manifest.get('purpose')!='public-setup-workspace-only' or manifest.get('workspace')!=str(workspace):
            raise ValueError('manifest scope')
        source=Path(manifest['source']);runner=workspace/(ATTEMPT+'-runner')
        if not source.is_absolute() or '..' in source.parts:raise ValueError('source')
        trusted(source,True);trusted(runner,True)
        if (runner/'.git').exists():trusted(runner/'.git')
        for label,value in inspect_objects(source,runner).items():print(label+':',value)
        print('PREFIX_INTENT:', 'PRESENT_PRESERVE' if os.path.lexists(workspace/(ATTEMPT+'-prefix-completion-intent.json')) else 'ABSENT')
        print('STAGING_RECEIPT:', 'PRESENT_PRESERVE' if os.path.lexists(workspace/(ATTEMPT+'-staging-receipt.json')) else 'ABSENT')
        print('READ_ONLY_COMPLETE: no fetch, checkout, writes, credential reads or staging')
        return 0
    except Exception:
        print('STOP: READ_ONLY_GIT_PROBE_UNVERIFIED; no changes made')
        return 1


if __name__=='__main__':raise SystemExit(main())
