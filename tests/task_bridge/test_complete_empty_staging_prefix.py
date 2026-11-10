import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest
from test_stage_from_cold_inputs import derived, cold, fixture, ROOT  # noqa: F401


def load(name, file):
    spec=importlib.util.spec_from_file_location(name,ROOT/'ops/bridge_one_shot'/file)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


@pytest.fixture
def prefix(derived, monkeypatch):
    original, workspace, getter, observed = derived
    original.prepare(str(workspace),'a'*40,{'41':6761280723,'45':6713729283},getter=getter,stage=True)
    (workspace/(original.ATTEMPT+'-staging-receipt.json')).unlink()  # offline simulated partial stage only
    v3=load('v3_fixture','operator_bootstrap_v3.py')
    for key in v3.PREFIX_KEYS:
        p=workspace/(original.ATTEMPT+'-'+key);p.mkdir(mode=0o700)
        uid,gid=(0,0) if key in ('bundle','runner','journal_parent') else (10000,10000)
        os.chown(p,uid,gid)
    m=load('prefix_entry','complete_empty_staging_prefix.py')
    original_load=m.load_public
    effects=[]
    def load_public(commit,name,getter):
        result=original_load(commit,name,getter)
        if name=='operator_bootstrap_v3.py':
            def stage(cfg, *, prepared_prefix=False):
                assert prepared_prefix is True
                result.validate_spec(cfg,prepared_prefix=True)
                effects.append(cfg)
                return 'STAGED ONLY offline final-effect callback'
            result.stage=stage
        if name=='prepare_private_enrollment.py':
            reader=result.root_bytes
            def read(path,limit):
                assert path.name not in ('manager-key.pem','root-github-token','worker-github-token')
                return reader(path,limit)
            result.root_bytes=read
        return result
    monkeypatch.setattr(m,'load_public',load_public)
    return m,workspace,getter,effects


def test_only_exact_empty_prefix_can_be_completed_and_originals_are_preserved(prefix):
    m,workspace,getter,effects=prefix
    saved={p.name:p.read_bytes() for p in workspace.iterdir() if p.is_file()}
    m.complete(str(workspace),'a'*40,getter=getter)
    assert effects==[]
    m.complete(str(workspace),'a'*40,apply=True,getter=getter)
    assert len(effects)==1
    for name,blob in saved.items(): assert (workspace/name).read_bytes()==blob
    receipt=json.loads((workspace/(m.ATTEMPT+'-staging-receipt.json')).read_text())
    assert receipt['activation'] is False and receipt['worker_credentials_installed'] is False
    with pytest.raises(m.Stop,match='RECEIPT_EXISTS'):m.complete(str(workspace),'a'*40,apply=True,getter=getter)
    assert len(effects)==1


@pytest.mark.parametrize('case',['nonempty','wrongmode','wrongowner','symlink','intent','changed_spec','changed_source'])
def test_prefix_refusals_precede_any_completion_effect(prefix,case):
    m,workspace,getter,effects=prefix
    runner=workspace/(m.ATTEMPT+'-runner')
    if case=='nonempty':(runner/'historical-receipt').write_text('preserve')
    elif case=='wrongmode':runner.chmod(0o755)
    elif case=='wrongowner':os.chown(runner,10000,10000)
    elif case=='symlink':runner.rmdir();runner.symlink_to(workspace,target_is_directory=True)
    elif case=='intent':(workspace/(m.ATTEMPT+'-prefix-completion-intent.json')).write_text('preserve')
    elif case=='changed_source':(workspace/(m.ATTEMPT+'-bootstrap.py')).write_text('unreviewed')
    else:
        p=workspace/(m.ATTEMPT+'-bootstrap-spec.json');d=json.loads(p.read_text());d['cursors']['41']+=1;p.write_text(json.dumps(d))
    with pytest.raises((m.Stop,ValueError,FileExistsError,PermissionError)):
        m.complete(str(workspace),'a'*40,apply=True,getter=getter)
    assert effects==[]
    assert not (workspace/(m.ATTEMPT+'-staging-receipt.json')).exists()


def test_v3_real_git_completion_preserves_order_and_never_runs_runtime(monkeypatch):
    import test_operator_bootstrap as old
    v3=load('bootstrap_v3','operator_bootstrap_v3.py')
    record=old.record
    def fixed_record(root):
        cfg=record(root)
        cfg['attempt']=v3.PREFIX_ATTEMPT
        for key in v3.PREFIX_KEYS:cfg[key]=str(root/'fresh'/(v3.PREFIX_ATTEMPT+'-'+key))
        cfg['plan']=str(root/'fresh'/(v3.PREFIX_ATTEMPT+'-operator-plan.json'))
        cfg['signer_policy']=str(root/'fresh'/(v3.PREFIX_ATTEMPT+'-signer-policy.json'))
        v3.SIGNER_STATE=str(root/'new-fixed-parent'/'claims')
        cfg['signer_state_root']=v3.SIGNER_STATE
        return cfg
    monkeypatch.setattr(old,'record',fixed_record)
    command=v3.command
    def names_only(argv,**kwargs):
        assert '{{json .Config.Env}}' not in argv
        if argv[:3]==['docker','image','inspect'] and argv[4].startswith('{{range'):
            return b'PATH\nHOME\n\n'
        return command(argv,**kwargs)
    v3.command=names_only
    mkdir=v3._mkdir
    parent_checks=[]
    def audited_mkdir(path,uid,gid):
        if str(path)==str(Path(v3.SIGNER_STATE).parent):
            intent=Path(path).parent/'fresh'/(v3.PREFIX_ATTEMPT+'-prefix-completion-intent.json')
            assert intent.exists()
            parent_checks.append(path)
        return mkdir(path,uid,gid)
    v3._mkdir=audited_mkdir
    stage=v3.stage
    def complete(cfg):
        for key in v3.PREFIX_KEYS:
            uid,gid=(0,0) if key in ('bundle','runner','journal_parent') else (cfg['uid'],cfg['gid'])
            v3._mkdir(Path(cfg[key]),uid,gid)
        return stage(cfg,prepared_prefix=True)
    v3.stage=complete
    # This inherited real-Git fixture substitutes ownership checks/transfer.
    # Actual prefix ownership/emptiness refusals run separately under root CI.
    def prefix_scope(cfg,paths):
        assert cfg['attempt']==v3.PREFIX_ATTEMPT
        for key in v3.PREFIX_KEYS:
            with os.scandir(paths[key]) as entries:assert next(entries,None) is None
    monkeypatch.setattr(v3,'_verify_prepared_prefix',prefix_scope)
    monkeypatch.setattr(old,'bootstrap',v3)
    old.test_stages_from_real_local_git_without_runtime_or_credential_values(monkeypatch)
    assert len(parent_checks)==1


def test_error_output_does_not_echo_exception_values(monkeypatch,capsys):
    m=load('prefix_sanitization','complete_empty_staging_prefix.py')
    monkeypatch.setattr(sys,'argv',['prefix','--workspace','/synthetic','--source-commit','a'*40,'--complete'])
    def fail(*a,**k):raise RuntimeError('OFFLINE_SECRET /private/path')
    monkeypatch.setattr(m,'complete',fail)
    assert m.main()==1
    out=capsys.readouterr().out
    assert 'TYPE=RuntimeError' in out and 'OFFLINE_SECRET' not in out and '/private/path' not in out


def test_existing_claim_and_untrusted_parent_are_never_adopted(prefix):
    m,workspace,getter,effects=prefix
    v3=load('prefix_parent_guard','operator_bootstrap_v3.py')
    cfg=json.loads((workspace/(m.ATTEMPT+'-bootstrap-spec.json')).read_text())
    claim_parent=workspace/'fixed-claim-parent'
    claim_parent.mkdir(mode=0o700)
    claims=claim_parent/'claims';claims.mkdir(mode=0o700)
    v3.SIGNER_STATE=str(claims);cfg['signer_state_root']=str(claims)
    with pytest.raises(FileExistsError):v3.stage(cfg,prepared_prefix=True)
    claims.rmdir();claim_parent.rmdir()  # synthetic empty test directories only
    claim_parent.symlink_to(workspace,target_is_directory=True)
    with pytest.raises(PermissionError):v3.stage(cfg,prepared_prefix=True)
    assert not (workspace/(m.ATTEMPT+'-prefix-completion-intent.json')).exists()
    assert claim_parent.is_symlink() and effects==[]


def test_documented_loader_parses_and_checks_digest_before_exec():
    import ast
    import subprocess
    doc=(ROOT/'ops/bridge_one_shot/COMPLETE_EMPTY_STAGING_PREFIX.md').read_text()
    block=doc.split('```bash\n',1)[1].split('```',1)[0]
    subprocess.run(['bash','-n'],input=block.encode(),check=True)
    code=block.split("<<'PY'\n",1)[1].rsplit('\nPY',1)[0]
    ast.parse(code)
    assert code.index('hashlib.sha256(source)') < code.index('exec(compile(source')
