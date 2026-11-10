import importlib.util
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT=Path(__file__).resolve().parents[2]


def load():
    spec=importlib.util.spec_from_file_location('git_probe',ROOT/'ops/bridge_one_shot/probe_staging_git.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def git(*argv):
    return subprocess.check_output(['git',*map(str,argv)],stderr=subprocess.DEVNULL)


def test_real_unreferenced_source_objects_are_not_carried_by_transport_clone(tmp_path):
    m=load();tree=tmp_path/'tree';tree.mkdir()
    git('-C',tree,'init','-q');(tree/'public').write_text('public fixture\n');git('-C',tree,'add','.')
    git('-C',tree,'-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','fixture')
    pin=git('-C',tree,'rev-parse','HEAD').decode().strip();source=tmp_path/'source.git'
    git('clone','--bare','-q',tree,source)
    for ref in git('--git-dir='+str(source),'for-each-ref','--format=%(refname)').decode().splitlines():
        git('--git-dir='+str(source),'update-ref','-d',ref)
    runner=tmp_path/'runner';git('clone','--no-local','--no-checkout','-q',source,runner)
    saved={str(p.relative_to(runner)):p.read_bytes() for p in runner.rglob('*') if p.is_file()}
    result=m.inspect_objects(source,runner,pin)
    assert result['SOURCE_CANDIDATE']=='PRESENT_COMMIT' and result['SOURCE_REFS']=='NONE'
    assert result['RUNNER_CANDIDATE']=='MISSING_OR_UNVERIFIED' and result['RUNNER_REFS']=='NONE'
    assert result['RUNNER_TREE']=='ONLY_GIT_DIRECTORY' and result['RUNNER_FETCH_HEAD']=='ABSENT'
    assert saved=={str(p.relative_to(runner)):p.read_bytes() for p in runner.rglob('*') if p.is_file()}
    # Offline candidate correction evidence only, never performed by the probe.
    git('-C',runner,'fetch','--no-tags','--no-write-fetch-head','--no-recurse-submodules',source,pin)
    assert m.inspect_objects(source,runner,pin)['RUNNER_CANDIDATE']=='PRESENT_COMMIT'
    assert not (runner/'.git/FETCH_HEAD').exists()
    assert git('-C',runner,'for-each-ref')==b''


def test_absent_runner_git_does_not_inspect_parent_repository(tmp_path,monkeypatch):
    m=load();calls=[]
    monkeypatch.setattr(m,'git_read',lambda argv:(calls.append(argv) or (0,b'commit')))
    runner=tmp_path/'runner';runner.mkdir()
    result=m.inspect_objects(tmp_path/'source.git',runner)
    assert result['RUNNER_GIT']=='ABSENT_OR_UNVERIFIED'
    assert all(argv[0]!='-C' for argv in calls)


def test_nonroot_stops_before_manifest_or_git(monkeypatch,capsys):
    m=load();monkeypatch.setattr(m.os,'geteuid',lambda:1000)
    monkeypatch.setattr(sys,'argv',['probe','--workspace','/synthetic'])
    monkeypatch.setattr(m,'git_read',lambda *_:pytest.fail('unexpected Git'))
    assert m.main()==1
    assert '/synthetic' not in capsys.readouterr().out


def test_documented_loader_syntax_and_hash_before_exec():
    import ast
    doc=(ROOT/'ops/bridge_one_shot/PROBE_STAGING_GIT.md').read_text()
    block=doc.split('```bash\n',1)[1].split('```',1)[0]
    subprocess.run(['bash','-n'],input=block.encode(),check=True)
    code=block.split("<<'PY'\n",1)[1].rsplit('\nPY',1)[0]
    ast.parse(code)
    assert code.index('hashlib.sha256(source)')<code.index('exec(compile(source')
