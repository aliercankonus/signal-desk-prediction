"""Inert review checks for the proposed one-shot environment; never start Docker/Bridge."""
from pathlib import Path
import ast
import importlib.util
import os
import socket
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

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


def test_network_preflight_checks_both_subnets_and_bridge_interfaces_offline():
    spec = importlib.util.spec_from_file_location('one_shot_network_preflight',
                                                  DESIGN / 'network_preflight.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    routes = [{'dst': '172.30.51.0/24'}]
    networks = [{'IPAM': {'Config': [{'Subnet': '172.30.50.0/24'}]}}]
    links = [{'ifname': 'br-sd-uplink'}]
    conflicts = module.check_proposals(routes, networks, links)
    assert 'worker_isolated: docker 172.30.50.0/24' in conflicts
    assert 'proxy_uplink: route 172.30.51.0/24' in conflicts
    assert 'proxy_uplink: host interface br-sd-uplink already exists' in conflicts
    assert module.check_proposals([], [], []) == []


def test_firewall_is_scoped_to_one_shot_network():
    text = (DESIGN / 'worker_firewall.sh').read_text()
    assert 'signal-desk-bridge-once' in text
    assert 'br-sd-once' in text
    assert 'SD_ONCE_FWD' in text
    assert 'AUTODEV_FWD' not in text
    assert 'iptables -F' not in text


def test_relay_drains_both_directions_under_forced_partial_writes():
    proxy = load_proxy()
    class ShortWriter:
        def __init__(self, sock):
            self.sock, self.calls = sock, 0
        def fileno(self): return self.sock.fileno()
        def setblocking(self, flag): return self.sock.setblocking(flag)
        def recv(self, size): return self.sock.recv(size)
        def shutdown(self, how): return self.sock.shutdown(how)
        def send(self, data):
            self.calls += 1
            if self.calls % 7 == 0:
                raise BlockingIOError()
            return self.sock.send(data[:17])

    client_peer, client_relay = socket.socketpair()
    upstream_relay, upstream_peer = socket.socketpair()
    sockets = (client_peer, client_relay, upstream_relay, upstream_peer)
    try:
        for sock in sockets:
            sock.settimeout(8)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1024)
        client, upstream = ShortWriter(client_relay), ShortWriter(upstream_relay)
        outbound = bytes(range(256)) * 512
        inbound = bytes(reversed(range(256))) * 512

        def send_then_eof(sock, payload):
            sock.sendall(payload)
            sock.shutdown(socket.SHUT_WR)

        def slow_receive(sock):
            chunks = []
            while chunk := sock.recv(113):
                chunks.append(chunk)
                time.sleep(0.0002)
            return b''.join(chunks)

        with ThreadPoolExecutor(max_workers=5) as pool:
            relay = pool.submit(proxy.relay_bidirectional, client, upstream,
                                buffer_limit=2048, idle_timeout=3, total_timeout=12)
            sent_c = pool.submit(send_then_eof, client_peer, outbound)
            sent_u = pool.submit(send_then_eof, upstream_peer, inbound)
            read_c = pool.submit(slow_receive, client_peer)
            read_u = pool.submit(slow_receive, upstream_peer)
            sent_c.result(timeout=10)
            sent_u.result(timeout=10)
            assert read_c.result(timeout=10) == inbound
            assert read_u.result(timeout=10) == outbound
            assert max(relay.result(timeout=10)) <= 2048
        assert client.calls > 100 and upstream.calls > 100
    finally:
        for sock in sockets:
            sock.close()


def test_relay_preserves_delayed_response_after_request_half_close():
    proxy = load_proxy()
    caller, client_relay = socket.socketpair()
    upstream_relay, remote = socket.socketpair()
    try:
        caller.settimeout(2)
        remote.settimeout(2)
        with ThreadPoolExecutor(max_workers=1) as pool:
            relay = pool.submit(proxy.relay_bidirectional, client_relay, upstream_relay,
                                buffer_limit=31, idle_timeout=1, total_timeout=4)
            caller.sendall(b'request' * 257)
            caller.shutdown(socket.SHUT_WR)
            request = bytearray()
            while part := remote.recv(97):
                request.extend(part)
            assert request == b'request' * 257
            remote.sendall(b'response' * 263)
            remote.shutdown(socket.SHUT_WR)
            response = bytearray()
            while part := caller.recv(101):
                response.extend(part)
            assert response == b'response' * 263
            assert max(relay.result(timeout=2)) <= 31
    finally:
        for sock in (caller, client_relay, upstream_relay, remote):
            sock.close()


def test_relay_total_deadline_wins_over_continuous_progress():
    proxy = load_proxy()
    caller, client_relay = socket.socketpair()
    upstream_relay, remote = socket.socketpair()
    stopped = threading.Event()
    def trickle():
        try:
            while not stopped.wait(0.01):
                caller.sendall(b'x')
        except OSError:
            pass
    thread = threading.Thread(target=trickle, daemon=True)
    try:
        remote.settimeout(1)
        thread.start()
        with pytest.raises(TimeoutError):
            proxy.relay_bidirectional(client_relay, upstream_relay,
                                      buffer_limit=32, idle_timeout=0.2, total_timeout=0.1)
        assert remote.recv(64)  # Progress occurred before the total deadline.
        caller.settimeout(1)
        assert caller.recv(1) == b''
    finally:
        stopped.set()
        thread.join(1)
        for sock in (caller, client_relay, upstream_relay, remote):
            sock.close()


def test_relay_idle_timeout_shuts_down_both_peers():
    proxy = load_proxy()
    client_peer, client_relay = socket.socketpair()
    upstream_relay, upstream_peer = socket.socketpair()
    try:
        with pytest.raises(TimeoutError):
            proxy.relay_bidirectional(client_relay, upstream_relay,
                                      buffer_limit=32, idle_timeout=0.05, total_timeout=1)
        client_peer.settimeout(1)
        upstream_peer.settimeout(1)
        assert client_peer.recv(1) == b''
        assert upstream_peer.recv(1) == b''
    finally:
        for sock in (client_peer, client_relay, upstream_relay, upstream_peer):
            sock.close()


def test_established_tunnel_error_never_appends_http_403():
    proxy = load_proxy()
    caller, server_side = socket.socketpair()
    upstream, remote = socket.socketpair()
    result = []
    def serve():
        try:
            proxy.Handler(server_side, (proxy.WORKER_ADDRESS, 12345), object())
        finally:
            server_side.close()
            result.append(True)
    try:
        with patch.object(proxy.socket, 'getaddrinfo', return_value=[
                 (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('140.82.112.3', 443))]), \
             patch.object(proxy.socket, 'create_connection', return_value=upstream), \
             patch.object(proxy, 'relay_bidirectional', side_effect=OSError('synthetic relay failure')):
            thread = threading.Thread(target=serve, daemon=True)
            thread.start()
            caller.settimeout(2)
            caller.sendall(b'CONNECT github.com:443 HTTP/1.1\r\nHost: github.com:443\r\n\r\n')
            response = bytearray()
            while chunk := caller.recv(1024):
                response.extend(chunk)
            thread.join(2)
            assert result and not thread.is_alive()
            assert bytes(response) == b'HTTP/1.1 200 Connection Established\r\n\r\n'
    finally:
        caller.close()
        remote.close()
        upstream.close()


def test_rejected_connect_still_receives_http_403():
    proxy = load_proxy()
    caller, server_side = socket.socketpair()
    def serve():
        try:
            proxy.Handler(server_side, (proxy.WORKER_ADDRESS, 12345), object())
        finally:
            server_side.close()
    try:
        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        caller.settimeout(2)
        caller.sendall(b'CONNECT forbidden.example:443 HTTP/1.1\r\n\r\n')
        response = caller.recv(1024)
        thread.join(2)
        assert not thread.is_alive()
        assert response.startswith(b'HTTP/1.1 403 Forbidden\r\n')
    finally:
        caller.close()
        server_side.close()


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


def test_proxy_uplink_is_dedicated_attempt_owned_bridge_not_default_bridge():
    design = yaml.safe_load((DESIGN / 'compose.yml').read_text())
    networks = design['networks']
    assert set(networks) == {'worker_isolated', 'proxy_uplink'}
    assert set(design['services']['bridge-once']['networks']) == {'worker_isolated'}
    assert set(design['services']['connect-proxy']['networks']) == set(networks)
    uplink = networks['proxy_uplink']
    assert uplink.get('external') is not True
    assert uplink['driver'] == 'bridge'
    assert uplink['internal'] is False
    assert uplink['enable_ipv6'] is False
    assert uplink['ipam']['config'] == [{'subnet': '172.30.51.0/28'}]
    assert uplink['driver_opts']['com.docker.network.bridge.name'] == 'br-sd-uplink'
    assert uplink.get('name') != 'bridge'


def test_cleanup_identifies_both_empty_attempt_networks_even_with_zero_proxy():
    spec = importlib.util.spec_from_file_location('one_shot_network_resources',
                                                  DESIGN / 'network_resources.py')
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for role, subnet, internal, interface in (
        ('worker_isolated', '172.30.50.0/28', True, 'br-sd-once'),
        ('proxy_uplink', '172.30.51.0/28', False, 'br-sd-uplink'),
    ):
        record = {
            'Id': role + '-id', 'Name': 'signal-desk-bridge-once_' + role,
            'Labels': {'com.docker.compose.project': 'signal-desk-bridge-once',
                       'com.docker.compose.network': role},
            'Driver': 'bridge', 'Internal': internal, 'EnableIPv6': False,
            'Options': {'com.docker.network.bridge.name': interface,
                        **({'com.docker.network.bridge.gateway_mode_ipv4': 'isolated'}
                           if internal else {})},
            'IPAM': {'Config': [{'Subnet': subnet}]}, 'Containers': {},
        }
        assert module.validate_attempt_network(record, role) == role + '-id'
        with pytest.raises(ValueError):
            module.validate_attempt_network({**record, 'Containers': {'foreign': {}}}, role)
        with pytest.raises(ValueError):
            module.validate_attempt_network({**record, 'Name': 'bridge'}, role)
        with pytest.raises(ValueError):
            module.validate_attempt_network({**record, 'Labels': {}}, role)


def test_host_procedure_removes_both_owned_networks_after_zero_proxy_startup():
    text = (DESIGN / 'network_acceptance_host.sh').read_text()
    assert 'worker_isolated proxy_uplink' in text
    assert 'network_resources.py" --role "$role"' in text
    assert 'ZERO_PROXY' in text
    assert 'docker network rm "$network_id"' in text
    assert 'docker compose down' not in text
    assert 'docker network rm bridge' not in text
    assert 'connect-proxy' in text and 'bridge-once bridge-once' not in text


def test_host_cleanup_attempts_other_empty_owned_network_after_one_mismatch():
    text = (DESIGN / 'network_acceptance_host.sh').read_text()
    cleanup_loop = text.split('# Network creation may have succeeded before proxy creation failed.', 1)[1]
    cleanup_loop = cleanup_loop.split('if [[ "$residual" == 0 ]]; then', 1)[0]
    assert 'for role in worker_isolated proxy_uplink; do' in cleanup_loop
    assert 'break' not in cleanup_loop


def test_host_cleanup_success_message_does_not_claim_two_networks_were_created():
    text = (DESIGN / 'network_acceptance_host.sh').read_text()
    assert 'CLEANUP VERIFIED: attempt-owned networks absent' in text
