#!/usr/bin/env python3
"""Read-only host gate: reject an overlapping proposed worker subnet."""
from __future__ import annotations
import ipaddress
import json
import subprocess
import sys

CANDIDATE = '172.30.50.0/28'


def check_overlap(candidate: str, routes: list[dict], networks: list[dict]) -> list[str]:
    proposed = ipaddress.ip_network(candidate, strict=True)
    conflicts = []
    for route in routes:
        dst = route.get('dst')
        if not dst:
            raise ValueError('route without destination; cannot establish non-overlap')
        if dst == 'default':
            continue  # The default route is not an allocated subnet.
        net = ipaddress.ip_network(dst, strict=False)
        if net.overlaps(proposed):
            conflicts.append(f'route {dst}')
    for network in networks:
        for entry in network['IPAM']['Config'] or []:
            subnet = entry.get('Subnet')
            if subnet and ipaddress.ip_network(subnet, strict=False).version == 4:
                if ipaddress.ip_network(subnet, strict=False).overlaps(proposed):
                    conflicts.append(f'docker {subnet}')
    return conflicts


def main() -> int:
    def query(*args: str) -> str:
        return subprocess.run(args, check=True, capture_output=True, text=True, timeout=20).stdout
    try:
        routes = json.loads(query('ip', '-j', '-4', 'route', 'show', 'table', 'all'))
        ids = query('docker', 'network', 'ls', '-q').split()
        if not ids:
            raise ValueError('Docker returned no networks; daemon identity not established')
        networks = json.loads(query('docker', 'network', 'inspect', *ids))
        conflicts = check_overlap(CANDIDATE, routes, networks)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(f'NO-GO: subnet preflight incomplete ({type(exc).__name__})', file=sys.stderr)
        return 2
    if conflicts:
        print('NO-GO: subnet overlaps ' + ', '.join(conflicts), file=sys.stderr)
        return 1
    print(f'PASS: {CANDIDATE} does not overlap host IPv4 routes or Docker network subnets at inspection time')
    return 0


if __name__ == '__main__':
    sys.exit(main())
