"""Execute the reviewed Bash lifecycle against synthetic children and fake host commands.

No Docker daemon, iptables, VPS, public socket, or provider is contacted.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import select
import socket
import subprocess
import sys

import pytest


DESIGN = Path(__file__).resolve().parents[2] / 'ops' / 'bridge_one_shot'
HOST_SCRIPT = DESIGN / 'network_acceptance_host.sh'
LIFECYCLE = DESIGN / 'canary_lifecycle.sh'
EXISTING_CONTAINER = 'e' * 64
EXISTING_NETWORK = 'f' * 64
WORKER_ID = 'a' * 64
UPLINK_ID = 'b' * 64


def network_record(role: str, *, occupied: bool = False) -> dict:
    worker = role == 'worker_isolated'
    return {
        'Id': WORKER_ID if worker else UPLINK_ID,
        'Name': f'signal-desk-bridge-once_{role}',
        'Labels': {'com.docker.compose.project': 'signal-desk-bridge-once',
                   'com.docker.compose.network': role},
        'Driver': 'bridge', 'Internal': worker, 'EnableIPv6': False,
        'Options': {'com.docker.network.bridge.name': 'br-sd-once' if worker else 'br-sd-uplink',
                    **({'com.docker.network.bridge.gateway_mode_ipv4': 'isolated'} if worker else {})},
        'IPAM': {'Config': [{'Subnet': '172.30.50.0/28' if worker else '172.30.51.0/28'}]},
        'Containers': {'foreign': {'IPv4Address': '172.30.50.4/28'}} if occupied else {},
    }


def run_lifecycle(tmp_path: Path, mode: str, *, occupied: bool = False,
                  stop_unconfirmed: bool = False) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    text = HOST_SCRIPT.read_text()
    # Run the actual cleanup function, without executing the host's root-only preflight/startup.
    cleanup = text.split('cleanup() {', 1)[1].split('\ntrap cleanup EXIT', 1)[0]
    script = '''set -euo pipefail
source "$LIFECYCLE"
PROJECT=signal-desk-bridge-once
IMAGE=sha256:synthetic
TOKEN=synthetic-token
FIX_NAME=synthetic-fixture
REVIEW="$DESIGN"
BASELINE="$EXISTING_CONTAINER"
NETWORK_BASELINE="$EXISTING_NETWORK"
PROXY_STARTED=1 FW_ATTEMPTED=1 FIX_ATTEMPTED=0 FIXTURE_PASSED=0 COUNTERS_OBSERVED=0
CANARY_OWNER_PID='' CANARY_READ_FD='' CANARY_WRITE_FD=''
timeout() { shift; "$@"; }
ip() { return 1; }
iptables() { return 1; }
bash() {
  if [[ "$1" == "$DESIGN/worker_firewall.sh" ]]; then printf 'firewall:%s\\n' "$2" >> "$EVENTS"; return 0; fi
  command bash "$@"
}
docker() {
  if [[ "$1 $2" == 'ps -aq' ]]; then return 0; fi
  if [[ "$1 $2" == 'ps -q' ]]; then printf '%s\\n' "$EXISTING_CONTAINER"; return 0; fi
  if [[ "$1 $2" == 'network ls' ]]; then
    if [[ "$*" == *'com.docker.compose.network=worker_isolated'* ]]; then
      [[ -f "$STATE/worker" ]] || printf '%s\\n' "$WORKER_ID"
    elif [[ "$*" == *'com.docker.compose.network=proxy_uplink'* ]]; then
      [[ -f "$STATE/uplink" ]] || printf '%s\\n' "$UPLINK_ID"
    else
      printf '%s\\n' "$EXISTING_NETWORK"
      [[ -f "$STATE/worker" ]] || printf '%s\\n' "$WORKER_ID"
      [[ -f "$STATE/uplink" ]] || printf '%s\\n' "$UPLINK_ID"
    fi
    return 0
  fi
  if [[ "$1 $2" == 'network inspect' ]]; then
    if [[ "$3" == "$WORKER_ID" ]]; then printf '%s\\n' "$WORKER_JSON"; return 0; fi
    if [[ "$3" == "$UPLINK_ID" ]]; then printf '%s\\n' "$UPLINK_JSON"; return 0; fi
  fi
  if [[ "$1 $2" == 'network rm' ]]; then
    if [[ "$3" == "$WORKER_ID" ]]; then touch "$STATE/worker"; printf 'removed:worker\\n' >> "$EVENTS"; return 0; fi
    if [[ "$3" == "$UPLINK_ID" ]]; then touch "$STATE/uplink"; printf 'removed:uplink\\n' >> "$EVENTS"; return 0; fi
  fi
  printf 'FORBIDDEN_DOCKER_CALL:%s\\n' "$*" >> "$EVENTS"
  return 98
}
cleanup() {''' + cleanup + '''
if [[ "$STOP_UNCONFIRMED" == 1 ]]; then canary_stop() { return 1; }; fi
trap cleanup EXIT
coproc CANARY {
  case "$MODE" in
    bind) printf 'BIND_FAILED\\n'; exit 2 ;;
    early) exit 0 ;;
    late) printf 'READY %s\\n' "$TOKEN"; sleep 0.05; exit 0 ;;
    zero) sleep 0.2 ;;
  esac
}
if ! canary_capture; then exit 17; fi
case "$MODE" in
  bind)
    if canary_read CANARY_LINE 1 && [[ "$CANARY_LINE" == BIND_FAILED ]]; then exit 18; fi
    exit 17 ;;
  early)
    if canary_read CANARY_LINE 1; then exit 91; fi
    exit 19 ;;
  late)
    canary_read CANARY_LINE 1 || exit 92
    [[ "$CANARY_LINE" == "READY $TOKEN" ]] || exit 93
    wait "$CANARY_OWNER_PID" || true
    canary_is_live && exit 94
    exit 23 ;;
  zero) exit 29 ;;
esac
'''
    env = {'PATH': os.environ['PATH'], 'DESIGN': str(DESIGN), 'LIFECYCLE': str(LIFECYCLE),
           'EXISTING_CONTAINER': EXISTING_CONTAINER, 'EXISTING_NETWORK': EXISTING_NETWORK,
           'WORKER_ID': WORKER_ID, 'UPLINK_ID': UPLINK_ID, 'MODE': mode,
           'WORKER_JSON': json.dumps([network_record('worker_isolated', occupied=occupied)]),
           'UPLINK_JSON': json.dumps([network_record('proxy_uplink')]),
           'STOP_UNCONFIRMED': '1' if stop_unconfirmed else '0',
           'STATE': str(tmp_path), 'EVENTS': str(tmp_path / 'events'),
           'BASH_ENV': '', 'ENV': '', 'PYTHONPATH': ''}
    result = subprocess.run(['bash', '--noprofile', '--norc', '-c', script], env=env,
                            capture_output=True, text=True, timeout=8, check=False)
    events = (tmp_path / 'events').read_text().splitlines() if (tmp_path / 'events').exists() else []
    return result, events


@pytest.mark.parametrize('mode,expected', [('bind', {17, 18}), ('early', {17, 19}),
                                           ('late', {23}), ('zero', {29})])
def test_offline_shell_lifecycle_preserves_error_and_cleans_both_networks(tmp_path, mode, expected):
    result, events = run_lifecycle(tmp_path, mode)
    assert result.returncode in expected, result.stderr
    assert 'unbound variable' not in result.stderr
    assert 'CLEANUP VERIFIED' in result.stdout
    assert events == ['firewall:status', 'firewall:rollback', 'removed:worker', 'removed:uplink']
    assert (tmp_path / 'worker').exists() and (tmp_path / 'uplink').exists()


def test_offline_shell_cleanup_preserves_occupied_network_but_removes_other(tmp_path):
    result, events = run_lifecycle(tmp_path, 'zero', occupied=True)
    assert result.returncode == 125, result.stderr
    assert 'CLEANUP/BASELINE UNCONFIRMED' in result.stderr
    assert 'removed:worker' not in events
    assert 'removed:uplink' in events
    assert not (tmp_path / 'worker').exists()
    assert (tmp_path / 'uplink').exists()
    assert not any('FORBIDDEN_DOCKER_CALL' in event for event in events)


def test_offline_shell_cleanup_preserves_networks_if_canary_stop_unconfirmed(tmp_path):
    result, events = run_lifecycle(tmp_path, 'zero', stop_unconfirmed=True)
    assert result.returncode == 125, result.stderr
    assert 'CLEANUP/BASELINE UNCONFIRMED' in result.stderr
    assert events == ['firewall:status', 'firewall:rollback']
    assert not (tmp_path / 'worker').exists() and not (tmp_path / 'uplink').exists()


def test_host_canary_uses_exercised_stable_lifecycle_instead_of_coproc_specials():
    text = HOST_SCRIPT.read_text()
    assert 'source "$REVIEW/canary_lifecycle.sh"' in text
    assert 'canary_capture ||' in text
    assert 'canary_read CANARY_LINE 5' in text
    assert 'canary_read CANARY_ACK 5' in text
    assert 'canary_is_live' in text
    assert 'CANARY_PID' not in text and '${CANARY[0]}' not in text
    assert '155s python3 -I -B -u "$REVIEW/host_canary.py"' in text
    assert 'select.select([listener, sys.stdin.buffer]' in (DESIGN / 'host_canary.py').read_text()


def test_real_canary_bind_failure_on_occupied_loopback_has_no_false_ready():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
        occupied.bind(('127.0.0.1', 0))
        occupied.listen(1)
        result = subprocess.run([sys.executable, '-I', '-B', '-u',
                                 str(DESIGN / 'host_canary.py'), '127.0.0.1',
                                 str(occupied.getsockname()[1]), 'offline-token'],
                                input='', capture_output=True, text=True, timeout=3, check=False)
    assert result.returncode == 2
    assert result.stdout == 'BIND_FAILED\n'


def test_real_canary_ready_and_stdin_stop_on_loopback_only():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reserved:
        reserved.bind(('127.0.0.1', 0))
        port = reserved.getsockname()[1]
    child = subprocess.Popen([sys.executable, '-I', '-B', '-u',
                              str(DESIGN / 'host_canary.py'), '127.0.0.1', str(port),
                              'offline-token'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
    try:
        assert child.stdout is not None
        assert select.select([child.stdout], [], [], 3)[0], 'canary readiness timed out'
        assert child.stdout.readline() == 'READY offline-token\n'
        remaining, errors = child.communicate(input='STOP offline-token\n', timeout=3)
        assert child.returncode == 0, errors
        assert remaining == ''
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=3)


def test_real_bash_coprocess_snapshot_and_stop_on_loopback_only():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reserved:
        reserved.bind(('127.0.0.1', 0))
        port = reserved.getsockname()[1]
    script = '''set -euo pipefail
source "$LIFECYCLE"
TOKEN=offline-token
coproc CANARY { exec timeout --signal=TERM --kill-after=1s 5s "$PY" -I -B -u "$CANARY_FILE" 127.0.0.1 "$PORT" "$TOKEN"; }
canary_capture
canary_read LINE 2
[[ "$LINE" == "READY $TOKEN" ]]
canary_is_live
canary_stop
printf 'STOPPED\\n'
'''
    env = {'PATH': os.environ['PATH'], 'LIFECYCLE': str(LIFECYCLE),
           'CANARY_FILE': str(DESIGN / 'host_canary.py'), 'PY': sys.executable,
           'PORT': str(port), 'BASH_ENV': '', 'ENV': ''}
    result = subprocess.run(['bash', '--noprofile', '--norc', '-c', script], env=env,
                            capture_output=True, text=True, timeout=4, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout == 'STOPPED\n'
