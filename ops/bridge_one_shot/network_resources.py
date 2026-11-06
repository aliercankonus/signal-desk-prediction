#!/usr/bin/env python3
"""Validate exactly one attempt-owned Docker network before use or removal.

Host-side only. Accepts bounded Docker inspect JSON on stdin; never changes Docker.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import sys

PROJECT = 'signal-desk-bridge-once'
NETWORKS = {
    'worker_isolated': ('172.30.50.0/28', 'br-sd-once', True),
    'proxy_uplink': ('172.30.51.0/28', 'br-sd-uplink', False),
}


def validate_attempt_network(record: dict, role: str, *, proxy_id: str | None = None) -> str:
    subnet, interface, internal = NETWORKS[role]
    if record.get('Name') != f'{PROJECT}_{role}':
        raise ValueError('network name is not attempt-owned')
    labels = record.get('Labels') or {}
    if labels.get('com.docker.compose.project') != PROJECT or labels.get('com.docker.compose.network') != role:
        raise ValueError('network labels are not attempt-owned')
    if record.get('Driver') != 'bridge' or record.get('Internal') is not internal or record.get('EnableIPv6') is not False:
        raise ValueError('unexpected network driver or isolation')
    config = (record.get('IPAM') or {}).get('Config') or []
    if len(config) != 1 or config[0].get('Subnet') != subnet:
        raise ValueError('unexpected network subnet')
    options = record.get('Options') or {}
    if options.get('com.docker.network.bridge.name') != interface:
        raise ValueError('unexpected network interface')
    if role == 'worker_isolated' and options.get('com.docker.network.bridge.gateway_mode_ipv4') != 'isolated':
        raise ValueError('worker gateway mode not isolated')
    containers = record.get('Containers') or {}
    if proxy_id is None:
        if containers:
            raise ValueError('network is not empty')
    else:
        if set(containers) != {proxy_id}:
            raise ValueError('unexpected network peer')
        address = containers[proxy_id].get('IPv4Address', '').split('/')[0]
        if ipaddress.ip_address(address) not in ipaddress.ip_network(subnet):
            raise ValueError('proxy address outside network subnet')
        if role == 'worker_isolated' and address != '172.30.50.3':
            raise ValueError('unexpected worker-facing proxy address')
    network_id = record.get('Id')
    if not isinstance(network_id, str) or not network_id:
        raise ValueError('missing network ID')
    return network_id


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--role', choices=NETWORKS, required=True)
    parser.add_argument('--proxy-id', help='require exactly this peer; omit for empty cleanup')
    args = parser.parse_args()
    try:
        payload = sys.stdin.buffer.read(65537)
        if len(payload) > 65536:
            raise ValueError('network inspect output exceeds bound')
        records = json.loads(payload)
        if not isinstance(records, list) or len(records) != 1:
            raise ValueError('expected one network record')
        print(validate_attempt_network(records[0], args.role, proxy_id=args.proxy_id))
    except (ValueError, TypeError, KeyError) as exc:
        print(f'NO-GO: attempt network validation failed ({type(exc).__name__})', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
