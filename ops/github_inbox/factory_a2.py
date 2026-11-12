"""Dormant a2 factory; does not enqueue/dispatch on import or construction."""
import importlib.util
import os
from pathlib import Path
import re

CAPTURE='/opt/child-capture-a2.py'

def production_bridge(entry,policy):
    from bridge_queue import BridgeQueue
    if (not all(isinstance(entry.get(k),str) and re.fullmatch('[0-9a-f]{32}',entry[k]) for k in ('id','bridge_run_id')) or
        entry.get('bridge_state')!='/state/queue/'+entry['id']+'/bridge'):raise ValueError('queue mapping')
    if entry.get('kind')!='bridge':raise ValueError('queue kind')
    spec=importlib.util.spec_from_file_location('reviewed_write_root','/opt/queued-write-root.py')
    write_root=importlib.util.module_from_spec(spec);spec.loader.exec_module(write_root)
    bridge=BridgeQueue.production_bridge(entry,policy)
    native_command=bridge.agent.command
    def command(prompt,worktree):
        # Keep the frozen CLI help and command contract checked. The separately
        # versioned wrapper adds explicit provider selection and safe capture.
        if str(prompt)!=entry['bridge_state']+'/prompt' or str(worktree)!=entry['bridge_state']+'/worktrees/'+entry['bridge_run_id']:raise ValueError('command mapping')
        native=native_command(prompt,worktree)
        expected=['hermes','chat','--query-file',str(prompt),'--oneshot','--quiet','--in',str(worktree),'--max-turns','12','--run-budget','600']
        if native!=expected:raise ValueError('native command drift')
        return ['/opt/hermes/.venv/bin/python','-I','-B',CAPTURE,'--capture-approved-child','--queue-id',entry['id'],'--run-id',entry['bridge_run_id']]
    bridge.agent.command=command
    original=bridge.once
    def once():
        with write_root.child_write_root(entry):return original()
    bridge.once=once
    return bridge
