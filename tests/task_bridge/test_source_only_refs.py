import importlib.util
from pathlib import Path

import pytest
import test_finish_cloned_staging as previous

ROOT=Path(__file__).resolve().parents[2]


def load(file):
    spec=importlib.util.spec_from_file_location(file[:-3],ROOT/'ops/bridge_one_shot'/file)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


@pytest.fixture
def checkpoint(monkeypatch):
    original_load=previous.load;original_git=previous.git;observed={}
    def version(file):
        return original_load('operator_bootstrap_v5.py' if file=='operator_bootstrap_v4.py' else file)
    def git(*args):
        if args[0]=='clone' and '--no-local' in args:
            source=Path(args[-2]);base=original_git('--git-dir='+str(source),'rev-parse','HEAD').decode().strip()
            original_git('--git-dir='+str(source),'update-ref','refs/remotes/archive/candidate',observed['pin'])
            original_git('--git-dir='+str(source),'update-ref','refs/pull/17/head',base)
            original_git('--git-dir='+str(source),'update-ref','refs/notes/review',base)
        value=original_git(*args)
        if args[0]=='-C' and args[-1]=='candidate' and 'commit' in args:
            observed['pin']=original_git('-C',args[1],'rev-parse','HEAD').decode().strip()
        return value
    monkeypatch.setattr(previous,'load',version);monkeypatch.setattr(previous,'git',git)
    yield from previous.checkpoint.__wrapped__(monkeypatch)


def test_actual_root_completion_preserves_source_only_refs_without_importing(checkpoint,monkeypatch):
    m,cfg,workspace,calls=checkpoint
    src=m._git_snapshot(Path(cfg['source']))[0]
    dst=m._git_snapshot(Path(cfg['runner'])/'.git')[0]
    assert b'refs/remotes/archive/candidate' in src and b'refs/pull/17/head' in src
    assert b'refs/remotes/archive/candidate' not in dst and b'refs/pull/17/head' not in dst
    previous.test_actual_root_git_completion_preserves_refs_source_and_transfers_last(checkpoint,monkeypatch)


def test_extra_runner_ref_remains_blocked_even_if_present_in_source_namespace(checkpoint):
    m,cfg,workspace,calls=checkpoint
    store=Path(cfg['runner'])/'.git';base=previous.git('--git-dir='+str(store),'rev-parse','HEAD').decode().strip()
    previous.git('--git-dir='+str(store),'update-ref','refs/remotes/archive/candidate',base)
    calls.clear()
    with pytest.raises(PermissionError):m.stage(cfg,cloned_checkpoint=True)
    assert not any('fetch' in a for a in calls)
    assert not (workspace/(m.PREFIX_ATTEMPT+'-git-completion-intent.json')).exists()


def test_source_replacement_ref_is_rejected_before_raw_git_or_writes(checkpoint):
    m,cfg,workspace,calls=checkpoint
    source=Path(cfg['source']);base=previous.git('--git-dir='+str(source),'rev-parse','HEAD').decode().strip()
    previous.git('--git-dir='+str(source),'update-ref','refs/replace/'+base,base)
    calls.clear()
    with pytest.raises(PermissionError,match='replacement ref'):m.stage(cfg,cloned_checkpoint=True)
    assert not any('fetch' in a for a in calls)
    assert not (workspace/(m.PREFIX_ATTEMPT+'-git-completion-intent.json')).exists()


def test_source_only_ref_delta_does_not_change_runner_or_other_gates():
    original=(ROOT/'ops/bridge_one_shot/operator_bootstrap_v4.py').read_text()
    revised=(ROOT/'ops/bridge_one_shot/operator_bootstrap_v5.py').read_text()
    a=original.index("        else:raise PermissionError('source ref outside normal clone')")
    b=original.index('    expected[head]',a)
    c=revised.index("        elif name.startswith(b'refs/replace/'):")
    d=revised.index('    expected[head]',c)
    assert original[:a]==revised[:c] and original[b:]==revised[d:]
    entry=load('finish_source_ref_staging.py')
    import hashlib
    assert entry.PUBLIC['operator_bootstrap_v5.py']==hashlib.sha256(revised.encode()).hexdigest()


def test_documented_source_ref_loader_parses_and_hash_precedes_execution():
    import ast,subprocess
    doc=(ROOT/'ops/bridge_one_shot/FINISH_SOURCE_REF_STAGING.md').read_text()
    block=doc.split('```bash\n',1)[1].split('```',1)[0]
    subprocess.run(['bash','-n'],input=block.encode(),check=True)
    code=block.split("<<'PY'\n",1)[1].rsplit('\nPY',1)[0]
    ast.parse(code)
    assert code.index('hashlib.sha256(source)')<code.index('exec(compile(source')
