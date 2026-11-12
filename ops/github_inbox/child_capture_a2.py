"""Dormant worker-only native CLI capture for one separately approved a2 task.

The frozen HermesAgent.execute remains the outer process-group/time supervisor.
This wrapper starts no new session/process group and never stores raw output.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import stat
import subprocess
import sys
import time

KINDS={'unclassified','cli_option_rejected','write_root_refused','http_401_observed','http_403_observed','http_429_observed'}


def pattern(data):
    text=data.decode('utf-8','replace')
    if 'outside HERMES_WRITE_SAFE_ROOT' in text:return 'write_root_refused'
    if ('Unsupported gateway CLI options' in text or 'unrecognized arguments:' in text or 'No such option:' in text):return 'cli_option_rejected'
    for code in (401,403,429):
        if re.search(r'(?:HTTP(?:Error)?[ :]+|status(?:_code)?["\s:=]+)'+str(code)+r'\b',text,re.I):return 'http_'+str(code)+'_observed'
    return 'unclassified'


def private_dir(path,uid):
    for p in (path,*path.parents):
        s=p.lstat()
        if not stat.S_ISDIR(s.st_mode) or s.st_uid not in (0,uid) or s.st_mode&0o022:raise ValueError('private ancestry')
    if path.lstat().st_uid!=uid or path.lstat().st_mode&0o077:raise ValueError('private state')


def write(path,data):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as f:json.dump(data,f,sort_keys=True);f.flush();os.fsync(f.fileno())
    fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)


def capture(argv,state,queue_id,run_id,*,uid=10000,launcher=subprocess.Popen):
    if os.geteuid()!=uid:raise PermissionError('worker identity')
    private_dir(state,uid)
    if not all(isinstance(s,str) and re.fullmatch('[0-9a-f]{32}',s) for s in (queue_id,run_id)):raise ValueError('run identity')
    # An existing intent or receipt refuses BEFORE a child, including an earlier
    # spawn error or forced termination. No automatic second model invocation.
    if os.path.lexists(state/'native-cli-exit.json'):raise FileExistsError('consumed native receipt')
    write(state/'native-cli-intent.json',dict(schema=1,queue_id=queue_id,run_id=run_id))
    started=time.monotonic();tail=bytearray();count=0
    child=launcher(argv,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
    # No start_new_session: all native descendants retain the frozen outer group.
    selector=selectors.DefaultSelector();selector.register(child.stderr,selectors.EVENT_READ)
    try:
        exited_at=None
        while selector.get_map():
            if child.poll() is not None:
                exited_at=exited_at or time.monotonic()
                if time.monotonic()-exited_at>0.5:break
            for key,_ in selector.select(timeout=0.2):
                chunk=os.read(key.fd,4096)
                if not chunk:selector.unregister(key.fileobj);continue
                count=min(2**31-1,count+len(chunk));tail.extend(chunk)
                if len(tail)>8192:del tail[:-8192]
        code=child.wait()
        receipt=dict(schema=1,queue_id=queue_id,run_id=run_id,exit_code=code if code>=0 else None,
            signal=-code if code<0 else None,duration_ms=min(3600000,int((time.monotonic()-started)*1000)),
            stderr_bytes=count,observed_stderr_pattern=pattern(bytes(tail)),
            evidence='native stderr pattern only; not verified quota, entitlement or exact cause')
        write(state/'native-cli-exit.json',receipt)
        return code if 0<=code<=255 else 1
    finally:
        selector.close();child.stderr.close()
        # On interruption/timeout the unchanged outer supervisor kills/reaps the
        # whole group. A missing receipt remains uncertain, never a success.


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--queue-id');p.add_argument('--run-id');p.add_argument('--capture-approved-child',action='store_true')
    a=p.parse_args()
    if not a.capture_approved_child:
        print('REVIEW ONLY: no child, provider, credential or runtime action');return 0
    try:
        if not all(isinstance(v,str) and re.fullmatch('[0-9a-f]{32}',v) for v in (a.queue_id,a.run_id)):raise ValueError()
        state=Path('/state/queue')/a.queue_id/'bridge';worktree=state/'worktrees'/a.run_id
        if os.environ.get('HERMES_WRITE_SAFE_ROOT')!=str(worktree):raise ValueError()
        argv=['hermes','chat','--query-file',str(state/'prompt'),'--oneshot','--quiet','--in',str(worktree),'--max-turns','12','--run-budget','600','--provider','openai-codex']
        return capture(argv,state,a.queue_id,a.run_id)
    except Exception:
        print('NATIVE_CHILD: BLOCKED_PRESERVE',file=sys.stderr);return 1

if __name__=='__main__':raise SystemExit(main())
