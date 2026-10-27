"""Local contract tests for the restricted SSH host gateway."""
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
DISPATCH = ROOT / "scripts/host-gateway-dispatch.sh"
GATEWAY = ROOT / "scripts/host-gateway.sh"
INSTALL = ROOT / "scripts/install-host-gateway.sh"


def run(script, args=(), env=None):
    return subprocess.run(["bash", str(script), *args], text=True, capture_output=True, env=env)


def test_dispatch_only_accepts_exact_operations(tmp_path):
    dispatch = tmp_path / "dispatch.sh"
    dispatch.write_text(DISPATCH.read_text().replace("/usr/bin/sudo", str(tmp_path / "sudo")))
    sudo = tmp_path / "sudo"
    sudo.write_text('#!/bin/sh\nprintf "%s\\n" "$*"\n')
    sudo.chmod(0o755)
    for op in ("status", "validate", "deploy"):
        env = {**os.environ, "SSH_ORIGINAL_COMMAND": op}
        result = run(dispatch, env=env)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == f"-n -- /usr/local/libexec/signal-desk/host-gateway {op}"
    for command in ("", "deploy --no-smoke", "status; id", "../deploy", " deploy", "validate\nstatus"):
        env = {**os.environ, "SSH_ORIGINAL_COMMAND": command}
        result = run(dispatch, env=env)
        assert result.returncode != 0, command
        assert not result.stdout


def test_root_gateway_rejects_arguments_before_any_command(tmp_path):
    for args in ((), ("deploy", "--ref", "main"), ("shell",), ("status;id",)):
        result = run(GATEWAY, args)
        assert result.returncode != 0, args


def test_root_gateway_requires_verified_release_before_compose(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    verifier = tmp_path / "verify"
    verifier.write_text(f'#!/bin/sh\nprintf "%s\\n" "{repo}" existing-project test-host\n')
    verifier.chmod(0o755)
    wrapper = tmp_path / "gateway.sh"
    wrapper.write_text(GATEWAY.read_text().replace(
        "/usr/bin/python3 /usr/local/libexec/signal-desk/release-guard.py", str(verifier)))
    for name, output in (("id", "0"), ("docker", "DOCKER:$*")):
        script = tmp_path / name
        script.write_text(f'#!/bin/sh\necho "{output}"\n')
        script.chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"}
    result = run(wrapper, ("status",), env)
    assert result.returncode == 0, result.stderr
    assert "DOCKER:" in result.stdout and "existing-project" in result.stdout
    verifier.write_text('#!/bin/sh\nexit 1\n')
    denied = run(wrapper, ("status",), env)
    assert denied.returncode != 0
    assert "DOCKER:" not in denied.stdout


def test_each_gateway_shell_script_has_valid_syntax():
    for name in ("host-gateway-dispatch.sh", "host-gateway.sh",
                 "install-host-gateway.sh", "prepare-host-release.sh"):
        result = subprocess.run(["bash", "-n", str(ROOT / "scripts" / name)],
                                text=True, capture_output=True)
        assert result.returncode == 0, (name, result.stderr)


def test_installer_has_no_deployment_side_effects_and_restricts_sudo():
    text = INSTALL.read_text()
    assert "docker compose up" not in text
    assert "docker group" not in text
    assert "NOPASSWD: ALL" not in text
    assert "host-gateway status" in text
    assert "host-gateway validate" in text
    assert "host-gateway deploy" in text
    assert "--key-fingerprint" in text
    assert "ssh-keygen -lf - -E sha256" in text
    assert 'restrict,command="/usr/bin/hostname"' in text
    assert text.index('mv -f -- "$auth_tmp" "$auth"') < text.index('mv -f -- "$sudo_tmp" /etc/sudoers.d/signal-desk-host-gateway')
    assert 'bash -n "$repo/scripts/host-gateway-dispatch.sh"' in text
    assert text.index('bash -n "$repo/scripts/host-gateway-dispatch.sh"') < text.index('chown root:root "$agent_home"')
    gateway = GATEWAY.read_text()
    assert "release-guard.py verify" in gateway
    assert "git fetch" not in gateway and "git checkout" not in gateway
    assert "compose build collector" in gateway
    assert gateway.index("compose build collector") < gateway.index("compose run --rm --no-deps collector")
