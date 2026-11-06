#!/usr/bin/env python3
"""Read-only host gate for both attempt-owned bridge networks."""
from __future__ import annotations
import ipaddress
import json
import subprocess
import sys

CANDIDATES = {
    'worker_isolated': ('172.30.50.0/28', 'br-sd-once'),
    'proxy_uplink': ('172.30.51.0/28', 'br-sd-uplink'),
}


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


def check_proposals(routes: list[dict], networks: list[dict], links: list[dict]) -> list[str]:
    conflicts = []
    occupied = {link['ifname'] for link in links}
    for name, (subnet, interface) in CANDIDATES.items():
        conflicts.extend(f'{name}: {item}' for item in check_overlap(subnet, routes, networks))
        if interface in occupied:
            conflicts.append(f'{name}: host interface {interface} already exists')
    proposed = [ipaddress.ip_network(subnet) for subnet, _ in CANDIDATES.values()]
    if proposed[0].overlaps(proposed[1]):
        conflicts.append('proposed network subnets overlap each other')
    return conflicts


def main() -> int:
    def query(*args: str) -> str:
        return subprocess.run(args, check=True, capture_output=True, text=True, timeout=20).stdout
    try:
        routes = json.loads(query('ip', '-j', '-4', 'route', 'show', 'table', 'all'))
        links = json.loads(query('ip', '-j', 'link', 'show'))
        ids = query('docker', 'network', 'ls', '-q').split()
        if not ids:
            raise ValueError('Docker returned no networks; daemon identity not established')
        networks = json.loads(query('docker', 'network', 'inspect', *ids))
        conflicts = check_proposals(routes, networks, links)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(f'NO-GO: subnet preflight incomplete ({type(exc).__name__})', file=sys.stderr)
        return 2
    if conflicts:
        print('NO-GO: subnet overlaps ' + ', '.join(conflicts), file=sys.stderr)
        return 1
    print('PASS: both attempt-owned subnets and bridge interfaces are unallocated at inspection time')
    return 0


if __name__ == '__main__':
    sys.exit(main())
