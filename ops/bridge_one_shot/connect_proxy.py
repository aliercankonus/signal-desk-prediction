#!/usr/bin/env python3
"""Credential-free CONNECT-only proxy for one Bridge task.

Based on the reviewed Codex proxy design; also allows GitHub Git/REST hosts.
TLS stays end-to-end: this is not a URL-path, API-action, or content policy.
"""
from __future__ import annotations
import ipaddress
import os
import re
import select
import socket
import socketserver
import sys
import time

ALLOWED_HOSTS = frozenset({'auth.openai.com', 'chatgpt.com',
                           'github.com', 'api.github.com'})
WORKER_ADDRESS = '172.30.50.2'
BIND_ADDRESS = '172.30.50.3'
PORT = 3128
MAX_HEADER = 4096
MAX_CONNECTIONS = 16
MAX_BUFFER = 65536


def relay_bidirectional(client, upstream, *, buffer_limit=MAX_BUFFER,
                        idle_timeout=180, total_timeout=3900) -> tuple[int, int]:
    """Drain two bounded queues; propagate EOF only after queued bytes are sent.

    Returns per-destination peak queued bytes for offline regression assertions.
    The relay owns socket shutdown, while the handler owns descriptor closure.
    """
    if not 0 < buffer_limit <= MAX_BUFFER or idle_timeout <= 0 or total_timeout <= 0:
        raise ValueError('invalid relay bounds')
    peers = (client, upstream)
    pending = {client: bytearray(), upstream: bytearray()}
    reading = {client: True, upstream: True}
    write_closed = {client: False, upstream: False}
    peak = {client: 0, upstream: 0}
    started = last_progress = time.monotonic()
    for sock in peers:
        sock.setblocking(False)
    try:
        while True:
            for source, destination in ((client, upstream), (upstream, client)):
                if not reading[source] and not pending[destination] and not write_closed[destination]:
                    destination.shutdown(socket.SHUT_WR)
                    write_closed[destination] = True
            if not any(reading.values()) and not any(pending.values()):
                return peak[client], peak[upstream]
            remaining = min(started + total_timeout, last_progress + idle_timeout) - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('relay deadline exceeded')
            readable = [source for source, destination in ((client, upstream), (upstream, client))
                        if reading[source] and len(pending[destination]) < buffer_limit]
            writable = [sock for sock in peers if pending[sock]]
            ready_read, ready_write, _ = select.select(readable, writable, [], remaining)
            for sock in ready_write:
                try:
                    sent = sock.send(pending[sock])
                except BlockingIOError:
                    continue
                if sent == 0:
                    raise ConnectionError('relay peer closed during write')
                del pending[sock][:sent]
                last_progress = time.monotonic()
            for source in ready_read:
                destination = upstream if source is client else client
                capacity = buffer_limit - len(pending[destination])
                if capacity <= 0:
                    continue
                try:
                    chunk = source.recv(min(65536, capacity))
                except BlockingIOError:
                    continue
                if chunk:
                    pending[destination].extend(chunk)
                    peak[destination] = max(peak[destination], len(pending[destination]))
                else:
                    reading[source] = False
                last_progress = time.monotonic()
    finally:
        for sock in peers:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def parse_connect_target(target: str) -> tuple[str, int]:
    if not re.fullmatch(r'[a-z0-9.-]+:443', target, re.ASCII):
        raise ValueError('not an exact HTTPS authority')
    host, port = target.rsplit(':', 1)
    if host not in ALLOWED_HOSTS:
        raise ValueError('host not allowed')
    return host, int(port)


def choose_public_address(records: list[tuple]) -> tuple[str, int]:
    if not records:
        raise ValueError('empty DNS answer')
    addresses = [entry[4] for entry in records]
    if any(not ipaddress.ip_address(addr[0]).is_global for addr in addresses):
        raise ValueError('non-public DNS answer')
    return addresses[0][:2]


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        client = self.request
        client.settimeout(10)
        if self.client_address[0] != WORKER_ADDRESS:
            return
        data = bytearray()
        established = False
        try:
            while not data.endswith(b'\r\n\r\n') and len(data) < MAX_HEADER:
                chunk = client.recv(1)
                if not chunk:
                    return
                data.extend(chunk)
            if not data.endswith(b'\r\n\r\n'):
                raise ValueError('header too large')
            lines = bytes(data).split(b'\r\n')
            if len(lines) < 2 or not lines[0].isascii():
                raise ValueError('invalid request')
            parts = lines[0].decode('ascii').split(' ')
            if len(parts) != 3 or parts[0] != 'CONNECT' or parts[2] != 'HTTP/1.1':
                raise ValueError('CONNECT required')
            host, port = parse_connect_target(parts[1])
            if any(line.lower().startswith(b'proxy-authorization:') for line in lines[1:]):
                raise ValueError('proxy credentials forbidden')
            records = socket.getaddrinfo(host, port, family=socket.AF_INET, type=socket.SOCK_STREAM)
            ip, resolved_port = choose_public_address(records)
            with socket.create_connection((ip, resolved_port), timeout=10) as upstream:
                # Even a partial 200 response forbids a later HTTP error in TLS bytes.
                established = True
                client.sendall(b'HTTP/1.1 200 Connection Established\r\n\r\n')
                relay_bidirectional(client, upstream)
        except (OSError, ValueError, UnicodeError):
            if not established:
                try:
                    client.sendall(b'HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n')
                except OSError:
                    pass
            # Never log target, headers, tokens, request bodies, or upstream exceptions.


class Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = MAX_CONNECTIONS

    def __init__(self, address, handler):
        self.slots = __import__('threading').BoundedSemaphore(MAX_CONNECTIONS)
        super().__init__(address, handler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            # Override socketserver's traceback-printing error handler: no request metadata in logs.
            self.finish_request(request, client_address)
            self.shutdown_request(request)
        except BaseException:
            self.shutdown_request(request)
        finally:
            self.slots.release()


if __name__ == '__main__':
    # Bind only the private worker bridge address, never the host or proxy uplink interface.
    try:
        with Server((BIND_ADDRESS, PORT), Handler) as server:
            print('Codex CONNECT proxy listening on private worker network', flush=True)
            server.serve_forever(poll_interval=1)
    except OSError:
        print('Codex CONNECT proxy could not bind; refusing startup', file=sys.stderr)
        sys.exit(1)
