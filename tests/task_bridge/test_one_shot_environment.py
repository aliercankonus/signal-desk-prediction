"""Inert review checks for the proposed one-shot environment; never start Docker/Bridge."""
from pathlib import Path
import ast
import importlib.util
import os
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
DESIGN = ROOT / 'ops' / 'bridge_one_shot'


def git(path, *args):
    return subprocess.run(['git', '-C', str(path), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def test_runner_local_identity_inherits_to_bridge_style_worktree(tmp_path):
    original = tmp_path / 'original'
    original.mkdir()
    git(original, 'init', '-q', '-b', 'main')
    git(original, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
        'commit', '--allow-empty', '-q', '-m', 'fixture')
    runner = tmp_path / 'runner'
    subprocess.run(['git', 'clone', '--no-hardlinks', '-q', str(original), str(runner)], check=True)
    git(runner, 'config', '--local', 'user.name', 'Hermes Agent')
    git(runner, 'config', '--local', 'user.email', 'hermes-agent@users.noreply.github.com')
    task = tmp_path / 'task'
    git(runner, 'worktree', 'add', '-q', '-b', 'task-smoke', str(task), 'HEAD')
    for field in ('GIT_AUTHOR_IDENT', 'GIT_COMMITTER_IDENT'):
        ident = git(task, '-c', 'user.useConfigOnly=true', 'var', field)
        assert 'Hermes Agent <hermes-agent@users.noreply.github.com>' in ident
    for key in ('user.name', 'user.email'):
        assert subprocess.run(['git', '-C', str(original), 'config', '--local', '--get', key],
                              capture_output=True).returncode == 1


def load_proxy():
    path = DESIGN / 'connect_proxy.py'
    spec = importlib.util.spec_from_file_location('one_shot_connect_proxy', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_proxy_limits_github_and_provider_destinations():
    proxy = load_proxy()
    for host in ('github.com', 'api.github.com', 'auth.openai.com', 'chatgpt.com'):
        assert proxy.parse_connect_target(f'{host}:443') == (host, 443)
    for target in ('github.com:80', 'gist.github.com:443', 'raw.githubusercontent.com:443',
                   'api.github.com.evil:443', '10.0.0.1:443', 'github.com:8443',
                   'metadata.google.internal:443', 'localhost:443'):
        with pytest.raises(ValueError):
            proxy.parse_connect_target(target)
    assert proxy.WORKER_ADDRESS == '172.30.50.2'
    assert proxy.BIND_ADDRESS == '172.30.50.3'


def test_proxy_rejects_mixed_public_and_private_dns_answers():
    import socket
    proxy = load_proxy()
    records = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('140.82.112.3', 443)),
               (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 443))]
    with pytest.raises(ValueError, match='non-public'):
        proxy.choose_public_address(records)


def test_caller_refuses_missing_approval_before_any_queue_write(tmp_path):
    env = dict(os.environ)
    env.pop('BRIDGE_ONCE_APPROVED', None)
    env['QUEUE_ROOT'] = str(tmp_path / 'no-queue')
    result = subprocess.run([sys.executable, '-I', '-B', str(DESIGN / 'bridge_once.py')],
                            env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert 'approval marker absent' in result.stderr
    assert not (tmp_path / 'no-queue').exists()


def test_caller_has_one_explicit_enqueue_and_dispatch_only():
    tree = ast.parse((DESIGN / 'bridge_once.py').read_text())
    calls = [node.func.attr for node in ast.walk(tree)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)]
    assert calls.count('enqueue') == 1
    assert calls.count('dispatch_one') == 1
    assert calls.index('enqueue') < calls.index('dispatch_one')
    assert 'execute_task' not in (DESIGN / 'bridge_once.py').read_text()


def test_network_preflight_rejects_overlapping_route_without_host_calls():
    spec = importlib.util.spec_from_file_location('one_shot_network_preflight',
                                                  DESIGN / 'network_preflight.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.check_overlap('172.30.50.0/28',
                                [{'dst': '172.30.50.0/24'}], []) == ['route 172.30.50.0/24']


def test_firewall_is_scoped_to_one_shot_network():
    text = (DESIGN / 'worker_firewall.sh').read_text()
    assert 'signal-desk-bridge-once' in text
    assert 'br-sd-once' in text
    assert 'SD_ONCE_FWD' in text
    assert 'AUTODEV_FWD' not in text
    assert 'iptables -F' not in text


def test_one_shot_compose_has_no_legacy_worker_or_unbounded_service():
    design = yaml.safe_load((DESIGN / 'compose.yml').read_text())
    services = design['services']
    assert set(services) == {'bridge-once', 'connect-proxy'}
    bridge = services['bridge-once']
    assert bridge['restart'] == 'no'
    assert bridge['read_only'] is True
    assert bridge['cap_drop'] == ['ALL']
    assert bridge['security_opt'] == ['no-new-privileges:true']
    assert bridge['entrypoint'] == ['/opt/hermes/.venv/bin/python']
    assert bridge['command'][-1] == '/opt/bridge-once.py'
    assert bridge['cpus'] <= 1.0 and bridge['mem_limit'] == '1536m' and bridge['pids_limit'] == 128
    assert bridge['networks']['worker_isolated']['ipv4_address'] == '172.30.50.2'
    assert design['networks']['worker_isolated']['internal'] is True
    assert not design['networks']['worker_isolated']['enable_ipv6']
    assert all(s['restart'] == 'no' and s['read_only'] is True for s in services.values())
    for s in services.values():
        assert not s.get('ports') and not s.get('privileged')
        for volume in s['volumes']:
            assert volume['bind']['create_host_path'] is False
            assert '/autonomous-development/tasks' not in volume['target']
            assert '/var/run/docker.sock' not in volume['target']
    assert all('orchestrator.py' not in str(s) and 'execute_task' not in str(s)
               for s in services.values())
