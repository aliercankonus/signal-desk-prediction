"""Opt-in continuous public-data collector; never an execution service."""
import asyncio
from dataclasses import asdict
import fcntl
import json
import math
from pathlib import Path
import shutil
import signal
import time
import uuid

from websockets.exceptions import ConnectionClosed, InvalidStatusCode

from signal_desk.collector import binance_collector as stream
from signal_desk.collector.order_book_state import OrderBookGap
from signal_desk.collector.recovery import RecoveryPolicy
from signal_desk.config.loader import validate_config


class StorageLimit(RuntimeError):
    pass


class StorageGuard:
    def __init__(self, config, interval):
        self.base = Path(config["storage"]["base_path"])
        self.raw = Path(config["storage"]["raw_path"])
        self.base.mkdir(parents=True, exist_ok=True)
        self.raw.mkdir(parents=True, exist_ok=True)
        self.limit = int(config["retention"]["raw_pool_gb"] * 1024 ** 3)
        self.disk_halt = float(config["alarms"]["disk_halt_pct"])
        if self.limit <= 0 or not 0 < self.disk_halt <= 100:
            raise ValueError("Invalid raw quota or disk HALT threshold")
        # One startup inventory; no full history scan in the event path.
        self.used = sum(f.stat().st_size for f in self.raw.rglob("*") if f.is_file())
        self.interval, self.last_check = interval, float("-inf")
        self.check(0)

    def check(self, next_bytes):
        if self.used + next_bytes > self.limit:
            raise StorageLimit("Raw storage quota reached; no automatic deletion")
        now = time.monotonic()
        if now - self.last_check >= self.interval:
            usage = shutil.disk_usage(self.base)
            if usage.used / usage.total * 100 >= self.disk_halt:
                raise StorageLimit("Filesystem disk HALT threshold reached")
            self.last_check = now


async def continuous_loop(config, policy, *, max_run_seconds=None):
    totals = {"total_written_events": 0, "total_depth_events": 0,
              "total_trade_events": 0, "gap_count": 0, "reconnect_count": 0}
    runtime = {"continuous": True, "policy": asdict(policy), **totals}
    config["_collector_runtime"] = runtime
    try:
        config["_storage_guard"] = StorageGuard(config, policy.storage_check_seconds)
    except (StorageLimit, OSError, ValueError) as exc:
        stream.write_status(config, "HALT", str(exc))
        print(json.dumps({"status": "HALT", "reason": str(exc)}), flush=True)
        return 3

    async def recover():
        failures = 0
        while True:
            runtime["session_id"] = uuid.uuid4().hex
            runtime["session_synchronized"] = False
            runtime["consecutive_failures"] = failures
            healthy_since = None

            def progress(stats):
                nonlocal healthy_since, failures
                runtime["session_synchronized"] = True
                now = time.monotonic()
                if healthy_since is None:
                    healthy_since = now
                if now - healthy_since >= policy.stable_reset_seconds:
                    failures = 0
                    runtime["consecutive_failures"] = 0

            try:
                stream.write_status(config, "CONNECTING", "opening_websocket")
                await stream.stream_session(config, None, on_progress=progress)
                raise stream.StreamSyncError("Stream session ended unexpectedly")
            except asyncio.CancelledError:
                raise
            except (stream.StreamSyncError, OrderBookGap, OSError, ConnectionClosed,
                    InvalidStatusCode, asyncio.TimeoutError) as exc:
                runtime["session_synchronized"] = False
                runtime["last_error_diagnostics"] = getattr(exc, "diagnostics", {})
                status_code = getattr(exc, "status_code", None)
                if status_code is None:
                    status_code = getattr(exc, "http_status", None)
                # Rate limits/bans and permanent HTTP failures require investigation.
                if status_code is not None and status_code < 500:
                    stream.write_status(config, "HALT", str(exc), http_status=status_code)
                    print(json.dumps({"status": "HALT", "reason": str(exc)}), flush=True)
                    return 3
                failures += 1
                runtime["consecutive_failures"] = failures
                runtime["gap_count"] += int(isinstance(exc, OrderBookGap))
                runtime["reconnect_count"] += 1
                if failures >= policy.max_failures:
                    stream.write_status(config, "HALT", "recovery_budget_exhausted",
                                        last_error=str(exc))
                    print(json.dumps({"status": "HALT", "reason": "recovery_budget_exhausted",
                                      **runtime}), flush=True)
                    return 3
                delay = policy.delay(failures)
                stream.write_status(config, "RESYNCING", str(exc), retry_in_seconds=delay)
                print(json.dumps({"status": "RESYNCING", "reason": str(exc),
                                  "retry_in_seconds": delay, **runtime}), flush=True)
                # Each retry opens a new WS, creates a new book and fetches a new snapshot.
                await asyncio.sleep(delay)
            except Exception as exc:
                # Schema, malformed data and persistent storage failures aren't network retries.
                stream.write_status(config, "HALT", str(exc))
                print(json.dumps({"status": "HALT", "reason": str(exc)}), flush=True)
                return 3

    worker = asyncio.create_task(recover())
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    installed = []
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
            installed.append(sig)
        except (NotImplementedError, RuntimeError):
            pass
    stopper = asyncio.create_task(stop.wait())
    try:
        done, _ = await asyncio.wait(
            [worker, stopper], timeout=max_run_seconds,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if worker in done:
            return await worker
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
        reason = "signal_received" if stopper in done else "max_run_seconds_reached"
        was_synchronized = runtime.get("session_synchronized", False)
        runtime["session_synchronized"] = False
        stream.write_status(config, "STOPPED", reason)
        print(json.dumps({"status": "STOPPED", "reason": reason, **runtime}), flush=True)
        return 0 if stopper in done or was_synchronized else 2
    finally:
        worker.cancel()
        stopper.cancel()
        await asyncio.gather(worker, stopper, return_exceptions=True)
        for sig in installed:
            loop.remove_signal_handler(sig)


def run_continuous(config_path, max_run_seconds=None):
    config = validate_config(config_path)
    policy = RecoveryPolicy.from_config(config)
    if max_run_seconds is not None and (not math.isfinite(max_run_seconds) or max_run_seconds <= 0):
        raise ValueError("--max-run-seconds must be finite and positive")
    base = Path(config["storage"]["base_path"]) / "status"
    base.mkdir(parents=True, exist_ok=True)
    # Refuse a second continuous writer on this shared data volume.
    with (base / "collector.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('{"status":"ERROR","reason":"continuous collector already running"}', flush=True)
            return 3
        return asyncio.run(continuous_loop(config, policy, max_run_seconds=max_run_seconds))

