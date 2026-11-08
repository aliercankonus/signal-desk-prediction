"""Static safety gates for future-only staging and disabled Compose."""
import ast
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / 'ops/bridge_one_shot/OPERATOR_INSTALL.md'
COMPOSE = ROOT / 'ops/bridge_one_shot/compose.operator.yml'


def test_staging_block_does_not_run_entry_or_start_docker():
    text = DOC.read_text()
    blocks = re.findall(r'```sh\n(.*?)\n```', text, re.S)
    assert len(blocks) == 2
    stage, invocation = blocks
    assert 'STAGED ONLY:' in stage and 'procedure not run' in stage
    assert '--execute' not in stage and 'docker compose up' not in stage
    assert 'operator_host.py" --execute' in invocation
    assert 'STOP pending manager/operator proof' in text
    result = subprocess.run(['bash', '-n'], input=stage, text=True,
                            capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    python = stage.split("<<'PY'\n", 1)[1].rsplit('\nPY', 1)[0]
    ast.parse(python)
    assert "git('cat-file','-s',args[1])" in python
    assert "if int(size) > 65536" in python
    assert "{'worker_probe.py', 'connect_proxy.py'}" in python
    assert "mode = 0o444 if path.name in worker_helpers else 0o600" in python
    assert 'os.fchmod(stream.fileno(), mode)' in python


def test_operator_compose_is_one_dormant_inbox_owner_without_signer_mount():
    text = COMPOSE.read_text()
    assert 'profiles: [execution]' in text and 'restart: "no"' in text
    assert 'inbox-worker:' in text and 'connect-proxy:' in text
    assert 'bridge_once_candidate' not in text and 'bridge-once:' not in text.split('services:', 1)[1]
    assert '/opt/worker-probe.py' in text and '/private/inbox' in text
    assert '/opt/bridge-readback.py' not in text
    assert 'bridge_readback.py' not in text  # Root-only verifier outside worker mounts
    assert '/private/signer' not in text and 'signer_key' not in text
    assert 'org.signal-desk.issue41.attempt' in text


def test_firewall_helper_pins_admin_path_and_checks_tools_before_network_actions():
    script = ROOT / 'ops/bridge_one_shot/worker_firewall.sh'
    text = script.read_text()
    result = subprocess.run(['bash', '-n', str(script)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert 'PATH=/usr/sbin:/sbin:/usr/bin:/bin' in text
    assert 'export PATH' in text
    assert 'command -v "$tool"' in text
    assert 'iptables ip docker python3 wc' in text
    assert text.index('command -v "$tool"') < text.index('case "$ACTION" in')
