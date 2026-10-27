"""Shell orchestration tests use fake Docker; no host services or apt are modified."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from signal_desk.tools.install_check import check_health, build_manifest


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def sandbox(tmp_path):
    repo = tmp_path / "project with spaces"
    shutil.copytree(ROOT, repo, ignore=shutil.ignore_patterns(
        "__pycache__", ".pytest_cache", ".git", ".env", "runtime"))
    (repo / ".git").mkdir()
    binaries = tmp_path / "bin"
    binaries.mkdir()
    log = tmp_path / "calls.jsonl"
    program = """#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
name=Path(sys.argv[0]).name
args=sys.argv[1:]
with open(os.environ["MOCK_CALLS"],"a") as f:f.write(json.dumps([name]+args)+"\\n")
if name=="systemd-detect-virt":
    sys.exit(0 if os.environ.get("MOCK_CONTAINER") else 1)
if name=="df":
    print("Filesystem 1024-blocks Used Available Capacity Mounted on")
    print("mock 200000000 100 150000000 1% /")
elif name=="git":
    clean=[]
    i=0
    while i<len(args):
        if args[i] in ("-c","-C"):i+=2
        else:clean.append(args[i]);i+=1
    if clean[:2]==["remote","get-url"]:print("https://github.com/aliercankonus/signal-desk-prediction.git")
    elif clean[:1]==["rev-parse"]:print("a"*40)
    elif clean[:1]==["diff"] and os.environ.get("MOCK_DIRTY"):sys.exit(1)
elif name=="docker":
    fail=os.environ.get("MOCK_FAIL","")
    if args[:1]==["info"]:
        if fail=="daemon":sys.exit(1)
    elif args[:1]==["ps"]:
        if os.environ.get("MOCK_COLLECTOR"):print("running-collector")
    elif args[:1]==["inspect"]:print("sha256:"+"a"*64)
    elif args[:2]==["image","inspect"]:print("sha256:"+"b"*64)
    elif args[:1]==["compose"]:
        if "up" in args and "--help" in args:print("--wait --wait-timeout")
        elif "ps" in args:print("api-container")
        elif fail=="build" and "build" in args:sys.exit(1)
        elif fail=="tests" and "pytest" in args:sys.exit(1)
        elif fail=="config" and "validate_all" in " ".join(args):sys.exit(1)
        elif fail=="stream" and "stream" in args:sys.exit(2)
        elif fail=="health" and "--health-url" in args:sys.exit(1)
        elif "install_check" in " ".join(args) and "--git-commit" in args:
            print(json.dumps({"status":"installation_smoke_passed"}))
        else:print("mock_ok")
"""
    for name in ("docker", "git", "systemd-detect-virt", "df"):
        path = binaries / name
        path.write_text(program)
        path.chmod(0o755)
    env = {**os.environ, "PATH": str(binaries) + os.pathsep + os.environ["PATH"],
           "MOCK_CALLS": str(log)}
    return repo, log, env


def invoke(sandbox, *args, extra=None, installer=False):
    repo, _, env = sandbox
    env = {**env, **(extra or {})}
    script = "install.sh" if installer else "deploy.sh"
    return subprocess.run(["bash", str(repo / "scripts" / script), *args],
                          cwd=repo, env=env, text=True, capture_output=True, timeout=20)


def calls(sandbox):
    _, log, _ = sandbox
    return [json.loads(line) for line in log.read_text().splitlines()]


def test_repeated_install_preserves_config_and_environment(sandbox):
    repo, _, _ = sandbox
    config = repo / "config/config.yaml"
    config.write_text(config.read_text() + "\n# user's settings\n")
    environment = repo / ".env"
    environment.write_text("PRIVATE_SETTING=keep-this\nCOMPOSE_PROJECT_NAME=signal-desk-prediction\nSDP_API_PORT=8080\nSDP_BIND_ADDRESS=127.0.0.1\n")
    before_config, before_env = config.read_bytes(), environment.read_bytes()
    first = invoke(sandbox)
    second = invoke(sandbox)
    assert first.returncode == second.returncode == 0, first.stdout + first.stderr
    assert config.read_bytes() == before_config
    assert environment.read_bytes() == before_env
    assert "PRIVATE_SETTING" not in first.stdout
    assert len(list((repo / "runtime/install").glob("*/manifest.json"))) == 2


def test_new_env_supports_custom_project_and_port(sandbox):
    result = invoke(sandbox, "--project", "isolated-test", "--port", "18080")
    assert result.returncode == 0, result.stdout + result.stderr
    env = (sandbox[0] / ".env").read_text()
    assert "COMPOSE_PROJECT_NAME=isolated-test" in env
    assert "SDP_API_PORT=18080" in env


def test_explicit_offline_mode_skips_only_public_smoke(sandbox):
    result = invoke(sandbox, "--no-smoke")
    assert result.returncode == 0, result.stdout + result.stderr
    history = calls(sandbox)
    assert any("pytest" in c for c in history)
    assert not any("--mode" in c and ("once" in c or "stream" in c) for c in history)
    assert any("--smoke" in c and c[c.index("--smoke")+1] == "0" for c in history)


@pytest.mark.parametrize("failure", ["daemon", "build", "config", "tests", "stream"])
def test_failure_prevents_api_deployment(sandbox, failure):
    result = invoke(sandbox, extra={"MOCK_FAIL": failure})
    assert result.returncode != 0
    launched = [c for c in calls(sandbox) if c[0] == "docker" and "up" in c and "--help" not in c]
    assert not launched


def test_wrong_container_environment_is_rejected(sandbox):
    result = invoke(sandbox, extra={"MOCK_CONTAINER": "1"})
    assert result.returncode != 0
    assert "not inside an agent container" in result.stderr
    assert not any(c[0] == "docker" and "build" in c for c in calls(sandbox))


def test_running_collector_blocks_deployment(sandbox):
    result = invoke(sandbox, extra={"MOCK_COLLECTOR": "1"})
    assert result.returncode != 0
    assert "A collector is running" in result.stderr


def test_health_failure_has_no_success_manifest(sandbox):
    result = invoke(sandbox, extra={"MOCK_FAIL": "health"})
    assert result.returncode != 0
    assert not list((sandbox[0] / "runtime/install").glob("*/manifest.json"))


def test_existing_checkout_install_does_not_reclone_or_install_docker(sandbox):
    result = invoke(sandbox, "--install-docker", installer=True)
    assert result.returncode == 0, result.stdout + result.stderr
    history = calls(sandbox)
    assert not any("clone" in c or c[0] in ("apt-get", "systemctl") for c in history)


def test_dirty_tracked_code_is_not_deployed(sandbox):
    result = invoke(sandbox, extra={"MOCK_DIRTY": "1"})
    assert result.returncode != 0
    assert "Tracked code changes" in result.stderr


def test_expected_host_is_checked_before_checkout_changes(sandbox):
    result = invoke(sandbox, "--expected-host", "definitely-not-this-host", installer=True)
    assert result.returncode != 0
    assert "Hostname does not match" in result.stderr
    assert not any("fetch" in c or "clone" in c for c in calls(sandbox))


def test_existing_bind_settings_are_not_silently_overwritten(sandbox):
    env = sandbox[0] / ".env"
    env.write_text("COMPOSE_PROJECT_NAME=signal-desk-prediction\nSDP_API_PORT=8080\nSDP_BIND_ADDRESS=127.0.0.1\n")
    original = env.read_bytes()
    result = invoke(sandbox, "--port", "18080")
    assert result.returncode != 0
    assert env.read_bytes() == original


@pytest.mark.parametrize("bad", [
    {"mode": "live"}, {"execution_enabled": True}, {"symbol": "ETHUSDT"},
    {"status": "error"}, {"exchange": "other"},
])
def test_health_requires_exact_paper_scope(bad):
    payload = {"status": "ok", "mode": "paper", "execution_enabled": False,
               "exchange": "binance", "symbol": "BTCUSDT", **bad}
    with pytest.raises(ValueError):
        check_health(payload)


def test_real_manifest_does_not_include_config_secrets(tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text((ROOT / "config/config.example.yaml").read_text())
    manifest = build_manifest(config, "a"*40, "test-project", False, "api-id", "collector-id")
    assert manifest["execution_enabled"] is False
    assert manifest["public_smoke_run"] is False
    assert "smoke_skipped" in manifest["status"]
    assert len(manifest["config_sha256"]) == 64
    assert "fees" not in manifest and "endpoints" not in manifest

