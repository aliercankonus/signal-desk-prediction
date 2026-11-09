"""Review-only checks of the exact copyable #41 operator entry, never the host."""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
PREP = ROOT / 'ops/bridge_one_shot/install_operator_bootstrap.sh'
PROCEDURE = ROOT / 'ops/bridge_one_shot/ROOT_OPERATOR_ENTRY.md'
BOOTSTRAP = ROOT / 'ops/bridge_one_shot/operator_bootstrap.py'
PINNED_SHA = 'e79f337fcbefc4f21f4d6d4abd2e30078227cb0913f242b552630fd110c1dd0d'


def blocks():
    text = PROCEDURE.read_text()
    return [fence.split('\n```', 1)[0] for fence in text.split('```bash\n')[1:]]


def installer_python():
    code = PREP.read_text().split("python3 -I -B -c '\n", 1)[1]
    return code.split("\n' \"$ENTRY\" \"$BLOB_SHA\"", 1)[0]


def test_exact_copyable_preparation_and_separate_staging_fences():
    prep, stage = blocks()
    assert prep == PREP.read_text().rstrip('\n')
    assert not any(re.match(r'^\d+\|', line) for fence in (prep, stage) for line in fence.splitlines())
    for fence in (prep, stage):
        subprocess.run(['bash', '-n'], input=fence.encode(), check=True, capture_output=True, timeout=15)
    assert '--stage --spec' not in prep and '--execute' not in prep
    assert stage.count('--stage --spec') == 1 and '--execute' not in stage
    between = PROCEDURE.read_text().split('```bash\n')[1].split('\n```', 1)[1]
    assert 'STOP for operator review' in between
    assert prep.splitlines()[-1].endswith('STOP for operator review.\\n\'')
    assert 'PATH=/usr/sbin:/sbin:/usr/bin:/bin' in prep
    assert 'timeout -k 2s 15s' in prep


def test_exact_fence_embedded_python_parses_without_executing():
    prep, _ = blocks()
    preflight = prep.split("<<'PY'\n", 1)[1].split('\nPY\n', 1)[0]
    ast.parse(preflight)
    ast.parse(installer_python())
    assert hashlib.sha256(BOOTSTRAP.read_bytes()).hexdigest() == PINNED_SHA
    assert PINNED_SHA in prep


def test_installer_rejects_digest_mismatch_without_creating_output(tmp_path):
    blob = bytearray(BOOTSTRAP.read_bytes())
    blob[0] ^= 1
    target = tmp_path / 'fresh.py'
    result = subprocess.run([sys.executable, '-I', '-B', '-c', installer_python(), str(target), PINNED_SHA],
        input=blob, capture_output=True, timeout=15)
    assert result.returncode != 0
    assert not target.exists()


def test_installer_refuses_existing_destination_without_overwrite(tmp_path):
    target = tmp_path / 'existing.py'
    target.write_bytes(b'old-review-byte-preserved')
    result = subprocess.run([sys.executable, '-I', '-B', '-c', installer_python(), str(target), PINNED_SHA],
        input=BOOTSTRAP.read_bytes(), capture_output=True, timeout=15)
    assert result.returncode != 0
    assert target.read_bytes() == b'old-review-byte-preserved'
