import asyncio
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from signal_desk.collector import binance_collector as stream
from signal_desk.collector import continuous as worker
from signal_desk.collector.recovery import RecoveryPolicy
from signal_desk.collector.order_book_state import OrderBookGap


@pytest.fixture
def config(tmp_path):
    cfg = yaml.safe_load(Path("config/config.example.yaml").read_text())
    cfg["storage"]["base_path"] = str(tmp_path)
    cfg["storage"]["raw_path"] = str(tmp_path / "raw")
    return cfg


def capture(monkeypatch):
    records = []
    monkeypatch.setattr(stream, "write_status",
                        lambda cfg, status, reason=None, **kw: records.append((status, reason, kw)))
    return records


def test_gap_and_disconnect_rebootstrap_with_backoff(monkeypatch, config):
    statuses = capture(monkeypatch)
    sessions, waits = [], []

    async def fake_session(cfg, max_events, on_progress=None):
        sessions.append(cfg["_collector_runtime"]["session_id"])
        if len(sessions) == 1:
            raise OrderBookGap("depth gap")
        if len(sessions) == 2:
            raise stream.StreamSyncError("connection closed")
        on_progress({})
        await asyncio.Event().wait()

    async def fake_sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr(stream, "stream_session", fake_session)
    monkeypatch.setattr(worker.asyncio, "sleep", fake_sleep)
    assert asyncio.run(worker.continuous_loop(config, RecoveryPolicy(), max_run_seconds=.02)) == 0
    assert len(set(sessions)) == 3
    assert waits == [1, 2]
    assert config["_collector_runtime"]["gap_count"] == 1
    assert statuses[-1][:2] == ("STOPPED", "max_run_seconds_reached")


def test_retry_budget_halts_and_never_resets_on_connection_alone(monkeypatch, config):
    statuses = capture(monkeypatch)
    attempts = []

    async def failure(*args, **kwargs):
        attempts.append(1)
        raise stream.StreamSyncError("no depth bridge")

    async def no_wait(seconds):
        pass

    monkeypatch.setattr(stream, "stream_session", failure)
    monkeypatch.setattr(worker.asyncio, "sleep", no_wait)
    assert asyncio.run(worker.continuous_loop(config, replace(RecoveryPolicy(), max_failures=3))) == 3
    assert len(attempts) == 3
    assert statuses[-1][:2] == ("HALT", "recovery_budget_exhausted")


def test_only_sustained_healthy_progress_resets_budget(monkeypatch, config):
    capture(monkeypatch)
    clock = [0.]
    attempts = []
    monkeypatch.setattr(worker, "time", SimpleNamespace(monotonic=lambda: clock[0]))

    async def session(cfg, maximum, on_progress=None):
        attempts.append(1)
        if len(attempts) == 1:
            raise stream.StreamSyncError("first failure")
        if len(attempts) == 2:
            on_progress({})
            clock[0] = 61.
            on_progress({})
            raise stream.StreamSyncError("failure after stable session")
        on_progress({})
        await asyncio.Event().wait()

    async def no_wait(seconds):
        pass

    monkeypatch.setattr(stream, "stream_session", session)
    monkeypatch.setattr(worker.asyncio, "sleep", no_wait)
    policy = replace(RecoveryPolicy(), max_failures=2)
    assert asyncio.run(worker.continuous_loop(config, policy, max_run_seconds=.02)) == 0
    assert len(attempts) == 3
    assert config["_collector_runtime"]["consecutive_failures"] == 1


@pytest.mark.parametrize("code", [418, 429, 403])
def test_permanent_http_failure_is_not_retried(monkeypatch, config, code):
    statuses = capture(monkeypatch)
    attempts = []

    async def failure(*args, **kwargs):
        attempts.append(1)
        raise stream.SnapshotRequestError(f"HTTP {code}", code)

    monkeypatch.setattr(stream, "stream_session", failure)
    assert asyncio.run(worker.continuous_loop(config, RecoveryPolicy())) == 3
    assert len(attempts) == 1
    assert statuses[-1][2]["http_status"] == code


def test_raw_budget_blocks_before_overwrite_or_deletion(config):
    config["retention"]["raw_pool_gb"] = 1 / 1024 ** 3
    guard = worker.StorageGuard(config, 5)
    with pytest.raises(worker.StorageLimit, match="quota"):
        guard.check(2)


def test_disk_threshold_blocks_startup(monkeypatch, config):
    monkeypatch.setattr(worker.shutil, "disk_usage",
                        lambda _: SimpleNamespace(total=100, used=96, free=4))
    with pytest.raises(worker.StorageLimit, match="disk HALT"):
        worker.StorageGuard(config, 5)


def test_storage_io_failure_does_not_enter_network_retry(monkeypatch, config):
    capture(monkeypatch)
    attempts = []

    async def failure(*args, **kwargs):
        attempts.append(1)
        raise stream.CollectorStorageError("disk full")

    monkeypatch.setattr(stream, "stream_session", failure)
    assert asyncio.run(worker.continuous_loop(config, RecoveryPolicy())) == 3
    assert len(attempts) == 1


def test_status_is_atomic_and_contains_recovery_state(config):
    config["_collector_runtime"] = {"gap_count": 3, "session_id": "test"}
    stream.write_status(config, "RESYNCING", "gap")
    path = Path(config["storage"]["base_path"]) / "status/collector_status.json"
    assert json.loads(path.read_text())["gap_count"] == 3
    assert not list(path.parent.glob("*.tmp"))


def test_snapshot_deadline_kills_and_reaps_request(monkeypatch):
    class Process:
        returncode = None
        killed = False

        async def communicate(self):
            if self.killed:
                self.returncode = -9
                return b"", b""
            await asyncio.Event().wait()

        def kill(self):
            self.killed = True

    child = Process()

    async def launch(*args, **kwargs):
        return child

    monkeypatch.setattr(stream.asyncio, "create_subprocess_exec", launch)
    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(stream.fetch_snapshot_async("https://example.test", "BTCUSDT", 5000, timeout=.01))
    assert child.killed and child.returncode == -9


@pytest.mark.parametrize("overrides", [
    {"max_failures": 0}, {"retry_initial_seconds": -1},
    {"retry_initial_seconds": 10, "retry_max_seconds": 1},
    {"unknown": 1}, {"stable_reset_seconds": float("nan")},
])
def test_invalid_recovery_policy_is_rejected(overrides):
    with pytest.raises(ValueError):
        RecoveryPolicy.from_config({"collector": overrides})


def test_graceful_deadline_cancels_active_session(monkeypatch, config):
    capture(monkeypatch)
    cancelled = []

    async def session(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)

    monkeypatch.setattr(stream, "stream_session", session)
    assert asyncio.run(worker.continuous_loop(config, RecoveryPolicy(), max_run_seconds=.01)) == 2
    assert cancelled == [True]

@pytest.mark.parametrize("http_status", [200, 429])
def test_real_snapshot_helper_process_with_local_http(http_status):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"lastUpdateId": 105, "bids": [], "asks": []}).encode()
            self.send_response(http_status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}"
        if http_status == 200:
            result = asyncio.run(stream.fetch_snapshot_async(url, "BTCUSDT", 5000))
            assert result["lastUpdateId"] == 105
        else:
            with pytest.raises(stream.SnapshotRequestError) as caught:
                asyncio.run(stream.fetch_snapshot_async(url, "BTCUSDT", 5000))
            assert caught.value.http_status == 429
    finally:
        server.shutdown()
        server.server_close()
        thread.join()

def test_second_continuous_writer_is_refused(monkeypatch, config):
    import fcntl
    monkeypatch.setattr(worker, "validate_config", lambda _: config)
    lock_path = Path(config["storage"]["base_path"]) / "status/collector.lock"
    lock_path.parent.mkdir(parents=True)
    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert worker.run_continuous("unused", max_run_seconds=.01) == 3


@pytest.mark.parametrize("duration", [float("nan"), float("inf"), -1])
def test_invalid_continuous_duration_is_rejected(monkeypatch, config, duration):
    monkeypatch.setattr(worker, "validate_config", lambda _: config)
    with pytest.raises(ValueError, match="finite and positive"):
        worker.run_continuous("unused", max_run_seconds=duration)



