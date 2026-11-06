#!/usr/bin/env python3
"""Owned private host canary for a separately authorized credential-free fixture."""
from __future__ import annotations

import select
import socket
import sys
import time


def main() -> int:
    ip, port, token = sys.argv[1], int(sys.argv[2]), sys.argv[3].encode('ascii')
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        try:
            listener.bind((ip, port))  # no SO_REUSEPORT or replacement listener
            listener.listen(4)
        except OSError:
            print('BIND_FAILED', flush=True)
            return 2
        print('READY ' + token.decode('ascii'), flush=True)
        end = time.monotonic() + 150
        while time.monotonic() < end:
            try:
                ready, _, _ = select.select([listener, sys.stdin.buffer], [], [], 2)
                if sys.stdin.buffer in ready:
                    command = sys.stdin.buffer.readline(128)
                    if not command or command == b'STOP ' + token + b'\n':
                        break
                if listener not in ready:
                    continue
                client, _ = listener.accept()
            except (socket.timeout, InterruptedError):
                continue
            with client:
                client.settimeout(2)
                try:
                    if client.makefile('rb').readline(128) == token + b'\n':
                        client.sendall(b'CANARY-OK ' + token + b'\n')
                        print('HOST_CANARY_CHALLENGE_OK', flush=True)
                except OSError:
                    pass
        return 0
    finally:
        listener.close()


if __name__ == '__main__':
    sys.exit(main())
