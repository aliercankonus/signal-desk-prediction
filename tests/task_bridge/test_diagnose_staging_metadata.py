import importlib.util
import json
import os
from pathlib import Path
import tempfile

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load():
    spec = importlib.util.spec_from_file_location('stage_metadata',ROOT/'ops/bridge_one_shot/diagnose_staging_metadata.py')
    m = importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def test_describe_does_not_follow_or_read_files(tmp_path):
    m = load()
    file = tmp_path/'private';file.write_text('OFFLINE_PRIVATE_CONTENT')
    link = tmp_path/'link';link.symlink_to(file)
    assert m.describe(link).startswith('SYMLINK')
    assert m.describe(file).startswith('FILE')
    assert m.describe(tmp_path/'absent') == 'ABSENT'
    assert 'OFFLINE_PRIVATE_CONTENT' not in m.describe(file)


@pytest.mark.parametrize('existing', [False,True])
def test_real_private_metadata_diagnostic_never_reads_credentials(existing, monkeypatch, capsys):
    if os.geteuid() != 0: pytest.skip('protected root ancestry required')
    m = load()
    with tempfile.TemporaryDirectory(dir=Path.home()) as tmp:
        workspace = Path(tmp);workspace.chmod(0o700)
        manifest = workspace/'setup-manifest.json'
        manifest.write_text(json.dumps({'venv_metadata':{'status':'READY_METADATA_ONLY','uid':10000,'gid':12345,'mode':448}}))
        manifest.chmod(0o600)
        secret = workspace/'manager-key.pem';secret.write_text('OFFLINE_NEVER_READ')
        if existing:
            (workspace/(m.ATTEMPT+'-bootstrap-spec.json')).write_text('OFFLINE_NEVER_READ')
            (workspace/(m.ATTEMPT+'-runner')).symlink_to(secret)
        original = m.os.open
        seen = []
        def limited(path, flags, **kwargs):
            assert Path(path) == manifest
            seen.append(path)
            return original(path, flags, **kwargs)
        monkeypatch.setattr(m.os,'open',limited)
        m.diagnose(str(workspace))
        monkeypatch.setattr(m.os,'open',original)
        output = capsys.readouterr().out
        assert len(seen) == 1 and 'VENV_GID: 12345' in output
        assert 'OFFLINE_NEVER_READ' not in output and str(workspace) not in output
        assert 'READ_ONLY_COMPLETE' in output
        assert ('STAGE_BOOTSTRAP_SPEC_JSON: FILE' if existing else 'STAGE_BOOTSTRAP_SPEC_JSON: ABSENT') in output


def test_nonroot_stops_before_reading_manifest(monkeypatch):
    m = load();monkeypatch.setattr(m.os,'geteuid',lambda:1000)
    with pytest.raises(ValueError): m.diagnose('/synthetic')


def test_documented_loader_syntax_and_digest_before_exec():
    import ast
    import subprocess
    doc=(ROOT/'ops/bridge_one_shot/DIAGNOSE_STAGING_METADATA.md').read_text()
    block=doc.split('```bash\n',1)[1].split('```',1)[0]
    subprocess.run(['bash','-n'],input=block.encode(),check=True)
    code=block.split("<<'PY'\n",1)[1].rsplit('\nPY',1)[0]
    ast.parse(code)
    assert code.index('hashlib.sha256(source)') < code.index('exec(compile(source')
