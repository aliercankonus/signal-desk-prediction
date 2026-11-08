"""Offline Docker-client timeout and exact-attempt child termination tests."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('operator_timeout_host', ROOT / 'ops/bridge_one_shot/operator_host.py')
host = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = host
SPEC.loader.exec_module(host)


def plan():
    return host.Plan(attempt='attempt1', bundle=Path('/review'), source=Path('/source'),
        merge='5a9c6f5ff4be1f161d817da127ca6799e4a21dfd',
        image='sha256:' + 'a' * 64, uid=10000, gid=10000,
        runner=Path('/runner'), state=Path('/state'), auth=Path('/auth'),
        context=Path('/context'), home=Path('/home'), venv=Path('/venv'),
        inbox=Path('/inbox'), signer_token=Path('/signer/token'),
        signer_key=Path('/signer/key'), signer_public=Path('/signer/public.pem'),
        signer_policy=Path('/signer/scope.json'), signer_state_root=host.SIGNER_STATE_ROOT,
        overall_seconds=3600, journal_parent=Path('/journals'))


class DockerClientTimeout:
    """A timed-out docker client leaves the simulated worker task running."""
    def __init__(self, *, stop_works=True):
        self.worker = 'a' * 64
        self.running = True
        self.stop_works = stop_works
        self.calls = []

    def __call__(self, argv, *, timeout, env=None, input=None):
        self.calls.append(tuple(argv))
        if argv[:3] == ['docker', 'inspect', '--type']:
            return json.dumps({'Id': self.worker, 'Image': plan().image,
                'Config': {'Labels': {'org.signal-desk.issue41.attempt': 'attempt1',
                    'com.docker.compose.project': 'signal-desk-bridge-once',
                    'com.docker.compose.service': 'inbox-worker'}},
                'State': {'Running': self.running}})
        if argv[:3] == ['docker', 'exec', self.worker]:
            raise TimeoutError('docker client timed out, child still running')
        if argv[:4] == ['docker', 'stop', '--time', '5']:
            if self.stop_works:
                self.running = False
            return self.worker
        raise AssertionError(f'unexpected command: {argv}')


def test_timed_out_docker_client_stops_exact_worker_and_observes_exit():
    fake = DockerClientTimeout()
    ops = host.HostOperations(plan(), runner=fake)
    ops.worker_id = fake.worker
    with pytest.raises(TimeoutError):
        ops._inbox('tick', timeout=1)
    assert fake.running is False
    assert any(call[:4] == ('docker', 'stop', '--time', '5') for call in fake.calls)
    assert ops.runtime_stopped is True


def test_failed_stop_never_claims_runtime_stopped():
    fake = DockerClientTimeout(stop_works=False)
    ops = host.HostOperations(plan(), runner=fake)
    ops.worker_id = fake.worker
    with pytest.raises((TimeoutError, ValueError)):
        ops._inbox('tick', timeout=1)
    assert fake.running is True
    assert ops.runtime_stopped is False
