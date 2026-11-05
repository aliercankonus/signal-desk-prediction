"""Offline policy tests. No Docker daemon, live auth, or Codex requests."""
import ipaddress
import json
import os
from pathlib import Path
import socket
import subprocess
import unittest
from unittest.mock import patch

from network_preflight import check_overlap
from codex_connect_proxy import parse_connect_target, choose_public_address, Handler

BASE = Path(__file__).parent


class NetworkPolicyTests(unittest.TestCase):
    def test_acceptance_probe_is_provider_free_and_checks_direct_and_proxy_paths(self):
        text = (BASE/'network_acceptance.py').read_text()
        for required in ('172.17.0.1', '172.16.0.1', '172.16.1.1', '169.254.169.254',
                         '1.1.1.1', 'evil.example', 'auth.openai.com', 'chatgpt.com',
                         'ssl.create_default_context'):
            self.assertIn(required, text)
        self.assertNotIn('Bearer ', text)
        self.assertNotIn('responses', text)

    def test_host_firewall_is_scoped_and_has_rollback(self):
        script = BASE/'worker_firewall.sh'
        self.assertEqual(subprocess.run(['bash','-n',str(script)],capture_output=True).returncode, 0)
        text = script.read_text()
        for required in ('DOCKER-USER', 'br-autodev', '172.30.50.2',
                         '172.30.50.3', 'rollback', 'INPUT', 'AUTODEV_FWD'):
            self.assertIn(required, text)
        self.assertNotIn('iptables -F INPUT', text)
        self.assertNotIn('iptables -F DOCKER-USER', text)

    def test_candidate_rejects_host_route_even_if_docker_networks_are_clear(self):
        self.assertEqual(check_overlap('172.30.50.0/28',
                                       [{'dst': '172.30.50.0/24'}, {'dst': 'default'}],
                                       [{'IPAM': {'Config': [{'Subnet': '172.16.0.0/24'}]}}]),
                         ['route 172.30.50.0/24'])

    def test_candidate_rejects_docker_subnet_and_clear_routes_pass(self):
        self.assertEqual(check_overlap('172.30.50.0/28', [{'dst': '172.17.0.0/16'}],
                                       [{'IPAM': {'Config': [{'Subnet': '172.30.50.0/24'}]}}]),
                         ['docker 172.30.50.0/24'])
        self.assertEqual(check_overlap('172.30.50.0/28',
                                       [{'dst': '172.17.0.0/16'}, {'dst': '172.16.1.0/24'}],
                                       [{'IPAM': {'Config': [{'Subnet': '172.16.0.0/24'}]}}]), [])

    def test_proxy_exact_hosts_https_only_and_no_credentials_in_target(self):
        for target in ('auth.openai.com:443', 'chatgpt.com:443'):
            self.assertEqual(parse_connect_target(target), (target.split(':')[0], 443))
        for target in ('evil.com:443', 'sub.chatgpt.com:443', 'chatgpt.com.evil.com:443',
                       'chatgpt.com:80', '172.30.50.1:443', '[::1]:443',
                       'user@chatgpt.com:443', 'chatgpt.com:443/path'):
            with self.subTest(target=target), self.assertRaises(ValueError):
                parse_connect_target(target)

    def test_proxy_refuses_private_dns_rebinding_and_selects_public_address(self):
        with self.assertRaises(ValueError):
            choose_public_address([(2, 1, 6, '', ('172.16.0.1', 443))])
        with self.assertRaises(ValueError):
            choose_public_address([(2, 1, 6, '', ('169.254.169.254', 443))])
        self.assertEqual(choose_public_address([(2, 1, 6, '', ('1.1.1.1', 443))]), ('1.1.1.1', 443))

    def test_proxy_rejects_prohibited_requests_before_dns_or_upstream_connection(self):
        for request in (b'CONNECT evil.example:443 HTTP/1.1\r\n\r\n',
                        b'CONNECT 172.16.0.1:443 HTTP/1.1\r\n\r\n',
                        b'CONNECT chatgpt.com:80 HTTP/1.1\r\n\r\n',
                        b'GET https://chatgpt.com/ HTTP/1.1\r\n\r\n'):
            with self.subTest(request=request):
                client, server = socket.socketpair()
                try:
                    client.settimeout(2)
                    client.sendall(request)
                    with patch('codex_connect_proxy.socket.getaddrinfo', side_effect=AssertionError('DNS reached')):
                        Handler(server, ('172.30.50.2', 4321), object())
                    self.assertIn(b'403 Forbidden', client.recv(256))
                finally:
                    client.close(); server.close()

    def test_manifest_worker_only_reaches_internal_proxy_and_proxy_has_no_secrets(self):
        env = dict(os.environ, HERMES_IMAGE_REF='sha256:' + '0'*64,
                   HERMES_UID='10000', HERMES_GID='10000', HERMES_CODE_HOST_PATH='/fixture/code',
                   HERMES_QUEUE_HOST_PATH='/fixture/queue', HERMES_CHECKPOINT_HOST_PATH='/fixture/cp',
                   HERMES_WORKER_HOME_HOST_PATH='/fixture/home', HERMES_CONFIG_HOST_PATH='/fixture/config',
                   HERMES_SKILLS_HOST_PATH='/fixture/skills', HERMES_MEMORIES_HOST_PATH='/fixture/memories',
                   HERMES_WORKSPACE_HOST_PATH='/fixture/repo', HERMES_WORKSPACE_PATH='/workspaces/repo')
        p = subprocess.run(['docker','compose','--profile','execution','-f',str(BASE/'compose.supervisor.yml'),
                            'config','--format','json'],env=env,capture_output=True,text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        config=json.loads(p.stdout)
        worker=config['services']['worker']; proxy=config['services']['codex-proxy']
        self.assertEqual(list(worker['networks']), ['worker_isolated'])
        self.assertEqual(worker['environment']['HTTPS_PROXY'], 'http://172.30.50.3:3128')
        self.assertTrue(config['networks']['worker_isolated']['internal'])
        self.assertEqual(config['networks']['worker_isolated']['ipam']['config'][0]['subnet'], '172.30.50.0/28')
        self.assertEqual(config['networks']['worker_isolated']['driver_opts']['com.docker.network.bridge.gateway_mode_ipv4'], 'isolated')
        self.assertEqual(proxy['networks']['worker_isolated']['ipv4_address'], '172.30.50.3')
        self.assertEqual(set(proxy['networks']), {'worker_isolated','proxy_uplink'})
        self.assertFalse(proxy.get('ports'))
        self.assertFalse(any('auth.json' in v['target'] for v in proxy.get('volumes', [])))
        self.assertEqual(config['services']['supervisor']['network_mode'], 'none')

if __name__ == '__main__': unittest.main()
