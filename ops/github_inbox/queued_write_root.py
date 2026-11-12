"""Dormant factory overlay for a separately authorized future Bridge attempt.

Not wired into the consumed #43 entry. No enqueue, retry or model call on import.
The frozen Bridge still owns preflight, child supervision and publication.
"""
from contextlib import contextmanager
import os
from pathlib import Path
import re


@contextmanager
def child_write_root(entry,queue=Path('/state/queue')):
    queue=Path(queue)
    if not queue.is_absolute() or '..' in queue.parts:raise ValueError('queue path')
    for key in ('id','bridge_run_id'):
        if not isinstance(entry.get(key),str) or not re.fullmatch('[0-9a-f]{32}',entry[key]):
            raise ValueError('queue/run identity')
    state=queue/entry['id']/'bridge'
    if entry.get('kind')!='bridge' or entry.get('bridge_state')!=str(state):raise ValueError('Bridge state mapping')
    # The ID/path is allocated by the existing durable BridgeQueue entry, never
    # inferred from issue text. Scope only the one actual child worktree.
    root=str(state/'worktrees'/entry['bridge_run_id'])
    old=os.environ.get('HERMES_WRITE_SAFE_ROOT')
    os.environ['HERMES_WRITE_SAFE_ROOT']=root
    try:yield root
    finally:
        if old is None:os.environ.pop('HERMES_WRITE_SAFE_ROOT',None)
        else:os.environ['HERMES_WRITE_SAFE_ROOT']=old


def production_bridge(entry,policy):
    from bridge_queue import BridgeQueue
    bridge=BridgeQueue.production_bridge(entry,policy)
    original=bridge.once
    def once():
        with child_write_root(entry):return original()
    bridge.once=once
    return bridge
