"""Local regression tests for immutable, root-approved release selection."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
GUARD_PATH = ROOT / "scripts/host_release_guard.py"
INSTALL = ROOT / "scripts/install-host-gateway.sh"


def guard():
    spec = importlib.util.spec_from_file_location("host_release_guard", GUARD_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def git(repo, *args):
    result = subprocess.run(["git", "-C", str(repo), *args], check=True,
                            text=True, capture_output=True)
    return result.stdout.strip()


@pytest.fixture
def protected_tmp_path():
    # ROOT is owner-writable but has protected ancestors in the collector image;
    # pytest's default /tmp is intentionally rejected by the production guard.
    with tempfile.TemporaryDirectory(prefix=".release-test-", dir=ROOT) as folder:
        yield Path(folder)


@pytest.fixture
def release(protected_tmp_path):
    repo = protected_tmp_path / "protected" / "release"
    repo.mkdir(parents=True)
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Local test")
    git(repo, "config", "user.email", "test@example.invalid")
    (repo / ".gitignore").write_text(".env\n")
    (repo / "config").mkdir()
    (repo / "config/config.yaml").write_text("project:\n  mode: paper\n  execution_enabled: false\n")
    (repo / ".env").write_text("COMPOSE_PROJECT_NAME=existing\nSDP_API_PORT=8080\nSDP_BIND_ADDRESS=127.0.0.1\n")
    (repo / "docker-compose.yml").write_text("services: {}\n")
    (repo / "code.py").write_text("value = 1\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "approved")
    sha = git(repo, "rev-parse", "HEAD")
    g = guard()
    manifest = {
        "repo": str(repo), "approved_commit": sha, "project": "existing",
        "expected_host": socket.gethostname(), "agent_container_id": "a" * 64,
        "env_sha256": hashlib.sha256((repo / ".env").read_bytes()).hexdigest(),
        "config_sha256": hashlib.sha256((repo / "config/config.yaml").read_bytes()).hexdigest(),
        "volume_identity": "approved-volume|created-at",
    }
    return repo, manifest, g


def test_clean_but_different_commit_is_rejected(release):
    repo, manifest, g = release
    g.verify_release(manifest, owner_uid=os.getuid(), mount_sources=[], observed_volume_identity=manifest["volume_identity"])
    (repo / "code.py").write_text("value = 2\n")
    git(repo, "add", "code.py")
    git(repo, "commit", "-qm", "unapproved")
    assert git(repo, "status", "--porcelain") == ""
    with pytest.raises(g.ReleaseError, match="approved commit"):
        g.verify_release(manifest, owner_uid=os.getuid(), mount_sources=[], observed_volume_identity=manifest["volume_identity"])


def test_writable_or_replaceable_release_inputs_are_rejected(release):
    repo, manifest, g = release
    g.verify_release(manifest, owner_uid=os.getuid(), mount_sources=[], observed_volume_identity=manifest["volume_identity"])
    path = repo / "code.py"
    path.chmod(0o666)
    with pytest.raises(g.ReleaseError, match="Writable"):
        g.verify_release(manifest, owner_uid=os.getuid(), mount_sources=[], observed_volume_identity=manifest["volume_identity"])
    path.chmod(0o644)
    parent = repo.parent
    parent.chmod(0o777)
    try:
        with pytest.raises(g.ReleaseError, match="Writable"):
            g.verify_release(manifest, owner_uid=os.getuid(), mount_sources=[], observed_volume_identity=manifest["volume_identity"])
    finally:
        parent.chmod(0o755)


def test_world_writable_tmp_ancestor_remains_rejected():
    if not Path("/tmp").stat().st_mode & 0o022:
        pytest.skip("/tmp is not group/world writable on this runner")
    g = guard()
    with tempfile.TemporaryDirectory(dir="/tmp") as folder:
        with pytest.raises(g.ReleaseError, match="Writable protected path: /tmp"):
            g.protected_path(folder, owner_uid=os.getuid())


def test_non_root_owned_release_is_rejected(release):
    repo, manifest, g = release
    if os.getuid() == 0:
        # The collector image runs as root: make only the fixture checkout
        # unapproved, without weakening the verifier's root-only policy.
        repo.chown(12345, -1)
    with pytest.raises(g.ReleaseError, match="Unapproved owner"):
        g.verify_release(manifest, owner_uid=0, mount_sources=[], observed_volume_identity=manifest["volume_identity"])


def test_symlinked_release_input_is_rejected(release, protected_tmp_path):
    repo, manifest, g = release
    external = protected_tmp_path / "mutable-code.py"
    external.write_text("value = 1\n")
    (repo / "code.py").unlink()
    (repo / "code.py").symlink_to(external)
    with pytest.raises(g.ReleaseError, match="Symlink"):
        g.verify_release(manifest, owner_uid=os.getuid(), mount_sources=[], observed_volume_identity=manifest["volume_identity"])


def test_release_inside_agent_mount_is_rejected(release):
    repo, manifest, g = release
    with pytest.raises(g.ReleaseError, match="agent mount"):
        g.verify_release(manifest, owner_uid=os.getuid(), mount_sources=[str(repo.parent)])


def test_replaced_data_volume_is_rejected(release):
    repo, manifest, g = release
    with pytest.raises(g.ReleaseError, match="data volume identity"):
        g.verify_release(manifest, owner_uid=os.getuid(), mount_sources=[],
                         observed_volume_identity="different-volume|created-at")


def test_agent_mount_on_privileged_settings_is_rejected(release):
    repo, manifest, g = release
    with pytest.raises(g.ReleaseError, match="agent mount"):
        g.verify_release(manifest, owner_uid=os.getuid(),
                         mount_sources=["/etc/signal-desk"],
                         settings_path="/etc/signal-desk/host-gateway.json",
                         observed_volume_identity=manifest["volume_identity"])


def test_modified_approved_configuration_is_rejected(release):
    repo, manifest, g = release
    (repo / ".env").write_text((repo / ".env").read_text() + "EXTRA=1\n")
    with pytest.raises(g.ReleaseError, match="hash"):
        g.verify_release(manifest, owner_uid=os.getuid(), mount_sources=[], observed_volume_identity=manifest["volume_identity"])


def test_invalid_dispatcher_syntax_stops_install_before_authorization(tmp_path):
    repo = tmp_path / "release"
    (repo / "scripts").mkdir(parents=True)
    (repo / ".git").mkdir()
    (repo / "scripts/host_release_guard.py").write_text("# not executed before syntax checks\n")
    (repo / "scripts/host-gateway-dispatch.sh").write_text("if then\n")
    (repo / "scripts/host-gateway.sh").write_text("#!/usr/bin/env bash\n")
    (repo / "scripts/prepare-host-release.sh").write_text("#!/usr/bin/env bash\n")
    settings = tmp_path / "approved.json"
    settings.write_text(json.dumps({"repo": str(repo), "approved_commit": "a" * 40,
                                    "project": "existing", "expected_host": "test-host"}))
    fake_id = tmp_path / "id"
    fake_id.write_text('#!/bin/sh\n[ "$1" = -u ] && echo 0\n')
    fake_id.chmod(0o755)
    marker = tmp_path / "authorization-writes"
    for name in ("install", "chown", "mv", "visudo"):
        command = tmp_path / name
        command.write_text(f'#!/bin/sh\nprintf "%s\\n" "{name}" >> "{marker}"\nexit 99\n')
        command.chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"}
    result = subprocess.run(["bash", str(INSTALL), "--settings", str(settings),
                             "--agent-user", "test-agent", "--key-comment", "test",
                             "--key-fingerprint", "SHA256:abc"], env=env,
                            text=True, capture_output=True)
    assert result.returncode != 0
    assert "syntax" in result.stderr.lower() or "unexpected token" in result.stderr.lower()
    assert not marker.exists(), "Installer attempted an authorization-changing command"
    assert not (tmp_path / "authorized_keys").exists()
    assert not (tmp_path / "sudoers").exists()
