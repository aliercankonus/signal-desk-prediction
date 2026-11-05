#!/usr/bin/env python3
"""Host-operator fixture only: network acceptance without credentials or model requests.

Run in a disposable container assigned 172.30.50.2, NEVER in the real worker.
A refused connection alone is inconclusive if no listener exists: compare with host
canaries and inspect effective routes/firewall counters before declaring PASS.
"""
import argparse
import socket
import ssl
import sys

PROXY = ('172.30.50.3', 3128)
DIRECT_DENIED = [('1.1.1.1', 443), ('172.30.50.1', 443),
                 ('169.254.169.254', 80)]


def connect_request(host: str) -> socket.socket:
    s = socket.create_connection(PROXY, timeout=8)
    if s.getsockname()[0] != '172.30.50.2':
        s.close()
        raise RuntimeError('not running from disposable worker-IP fixture')
    s.settimeout(8)
    s.sendall(f'CONNECT {host}:443 HTTP/1.1\r\nHost: {host}:443\r\n\r\n'.encode('ascii'))
    response = bytearray()
    while not response.endswith(b'\r\n\r\n') and len(response) < 1024:
        char = s.recv(1)
        if not char: break
        response.extend(char)
    if not response.startswith(b'HTTP/1.1 200 '):
        s.close()
        raise RuntimeError('proxy CONNECT denied')
    return s


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--approved-fixture', action='store_true', required=True)
    parser.add_argument('--host-canary', required=True,
                        help='Host-side SYN-accepting fixture IP:port; no production target')
    args = parser.parse_args()
    failures = []
    try:
        with socket.create_connection(PROXY, timeout=4) as probe:
            if probe.getsockname()[0] != '172.30.50.2':
                raise RuntimeError('fixture is not at the worker IP')
    except (OSError, RuntimeError) as exc:
        print(f'NO-GO: fixture cannot reach proxy ({type(exc).__name__})', file=sys.stderr)
        return 2
    for host,port in DIRECT_DENIED:
        try:
            with socket.create_connection((host,port),timeout=2):
                failures.append(f'direct connection succeeded: {host}:{port}')
        except (OSError, TimeoutError):
            pass
    if args.host_canary:
        host,port=args.host_canary.rsplit(':',1)
        try:
            with socket.create_connection((host,int(port)),timeout=2):
                failures.append('host canary reached')
        except (OSError, TimeoutError):
            pass
    for host in ('evil.example', '172.16.0.1', 'chatgpt.com.evil.example'):
        try:
            with connect_request(host):
                failures.append('unauthorized proxy destination accepted')
        except (OSError, RuntimeError):
            pass
    for host in ('auth.openai.com', 'chatgpt.com', 'github.com', 'api.github.com'):
        try:
            with connect_request(host) as raw:
                # TLS handshake only: sends no HTTP request, token or model payload.
                with ssl.create_default_context().wrap_socket(raw,server_hostname=host):
                    pass
        except (OSError, RuntimeError, ssl.SSLError) as exc:
            failures.append(f'allowed TLS handshake failed: {host} ({type(exc).__name__})')
    if failures:
        print('NO-GO: ' + '; '.join(failures),file=sys.stderr)
        return 1
    print('Fixture probes passed; host canary/listener and firewall counter evidence still required')
    return 0

if __name__ == '__main__':
    sys.exit(main())
