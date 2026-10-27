import asyncio
import json
import threading

import pytest

from signal_desk.collector import binance_collector as collector


def depth(first, final):
    return json.dumps({"stream": "btcusdt@depth", "data": {
        "e": "depthUpdate", "E": 1, "U": first, "u": final,
        "b": [["10", "2"]], "a": []}})


def trade():
    return json.dumps({"stream": "btcusdt@trade", "data": {
        "e": "trade", "E": 1, "T": 1, "t": 1, "p": "10",
        "q": "1", "m": False}})


class FakeSocket:
    def __init__(self, messages):
        self.messages = asyncio.Queue()
        for message in messages:
            self.messages.put_nowait(message)
        self.opened = False
        self.closed = False
        self.seen = 0
        self.during_snapshot = threading.Event()

    async def __aenter__(self):
        self.opened = True
        return self

    async def __aexit__(self, *args):
        self.closed = True

    def __aiter__(self):
        return self

    async def __anext__(self):
        raw = await self.messages.get()
        self.seen += 1
        if self.seen >= 2:
            self.during_snapshot.set()
        return raw


def setup(monkeypatch, ws, snapshots):
    config = {
        "exchange": {
            "symbol": "BTCUSDT",
            "endpoints": {"rest_base_url": "https://example.test", "ws_base_url": "wss://example.test"},
            "market_data": {"snapshot_limit": 5000, "depth_stream": "btcusdt@depth", "trade_stream": "btcusdt@trade"},
        },
    }
    writes, statuses, calls = [], [], []
    values = iter(snapshots)
    monkeypatch.setattr(collector, "validate_config", lambda _: config)
    monkeypatch.setattr(collector.websockets, "connect", lambda *a, **kw: ws)
    monkeypatch.setattr(collector, "write_event", lambda c, e: writes.append(e.copy()))
    monkeypatch.setattr(collector, "write_status", lambda c, s, r=None, **kw: statuses.append((s, r, kw)))
    monkeypatch.setattr(collector, "STREAM_WAIT_SECONDS", 0.05)

    def snapshot(*args):
        assert ws.opened, "REST must follow WebSocket connect"
        assert ws.seen >= 1, "REST must follow first buffered depth"
        calls.append(args)
        return {"lastUpdateId": next(values), "bids": [["10", "1"]], "asks": [["11", "1"]]}

    monkeypatch.setattr(collector, "fetch_depth_snapshot", snapshot)
    async def async_snapshot(*args, **kwargs):
        return await asyncio.to_thread(collector.fetch_depth_snapshot, *args)
    monkeypatch.setattr(collector, "fetch_snapshot_async", async_snapshot)
    return writes, statuses, calls, snapshot


def run():
    return asyncio.run(collector.run_stream_async("unused", max_events=3))


def test_buffers_during_rest_and_preserves_previous_id(monkeypatch, capsys):
    async def scenario():
        ws = FakeSocket([depth(99, 100)])
        writes, statuses, calls, snapshot = setup(monkeypatch, ws, [105])
        loop = asyncio.get_running_loop()

        def slow_snapshot(*args):
            # REST waits until WS receiver has actually consumed another event.
            loop.call_soon_threadsafe(ws.messages.put_nowait, depth(105, 107))
            assert ws.during_snapshot.wait(1), "REST blocked the WS receiver"
            loop.call_soon_threadsafe(ws.messages.put_nowait, trade())
            return snapshot(*args)

        monkeypatch.setattr(collector, "fetch_depth_snapshot", slow_snapshot)
        code = await collector.run_stream_async("unused", max_events=3)
        # No receiver task leaks out of the collector.
        assert not [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        return code, ws, writes, statuses

    code, ws, writes, statuses = asyncio.run(scenario())
    assert code == 0 and ws.closed
    assert [e["event_type"] for e in writes] == ["book_snapshot", "book_delta", "trade"]
    assert writes[1]["previous_final_update_id"] == 105
    assert writes[1]["final_update_id"] == 107
    assert statuses[-1][2]["stale_depth_events"] == 1
    assert json.loads(capsys.readouterr().out)["gap_count"] == 0


def test_old_snapshot_retried_without_reconnecting(monkeypatch):
    ws = FakeSocket([depth(103, 104), depth(105, 106), trade()])
    writes, statuses, calls, _ = setup(monkeypatch, ws, [101, 104])
    assert run() == 0
    assert len(calls) == 2
    assert writes[0]["last_update_id"] == 104
    assert any(reason == "snapshot_behind_buffer" for _, reason, _ in statuses)


def test_real_gap_still_fails_closed_and_prints_reason(monkeypatch, capsys):
    ws = FakeSocket([depth(99, 100), depth(108, 109)])
    writes, statuses, _, _ = setup(monkeypatch, ws, [105])
    assert run() == 2
    assert len(writes) == 1  # Neither stale delta nor broken delta written.
    assert statuses[-1][0] == "RESYNCING"
    assert statuses[-1][2]["gap_count"] == 1
    assert "expected 106" in json.loads(capsys.readouterr().out)["reason"]
    assert ws.closed


def test_trade_only_stream_never_reports_success(monkeypatch):
    ws = FakeSocket([trade(), trade()])
    writes, statuses, calls, _ = setup(monkeypatch, ws, [105])
    assert run() == 2
    assert not writes and not calls
    assert not any(s == "RUNNING" for s, _, _ in statuses)


def test_snapshot_retry_budget_is_bounded(monkeypatch):
    ws = FakeSocket([depth(103, 104)])
    _, statuses, calls, _ = setup(monkeypatch, ws, [100, 101, 102])
    assert run() == 2
    assert len(calls) == collector.SNAPSHOT_ATTEMPTS
    assert "remained behind" in statuses[-1][1]


def test_buffer_overflow_is_explicit_and_cleans_up(monkeypatch):
    ws = FakeSocket([depth(1, 2)] * (collector.STREAM_BUFFER_LIMIT + 2))
    _, statuses, _, _ = setup(monkeypatch, ws, [105])
    assert run() == 2
    assert "overflow" in statuses[-1][1]
    assert ws.closed


def test_duplicate_depth_is_not_written_twice(monkeypatch):
    ws = FakeSocket([depth(99, 100), depth(106, 107), depth(106, 107), trade()])
    writes, statuses, _, _ = setup(monkeypatch, ws, [105])
    assert run() == 0
    assert sum(e["event_type"] == "book_delta" for e in writes) == 1
    assert statuses[-1][2]["stale_depth_events"] == 2


def test_socket_error_is_reported_and_not_swallowed(monkeypatch, capsys):
    ws = FakeSocket([depth(99, 100)])
    setup(monkeypatch, ws, [105])

    def broken_connection(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(collector.websockets, "connect", broken_connection)
    assert run() == 1
    assert json.loads(capsys.readouterr().out)["reason"] == "connection refused"


def test_server_shutdown_requires_new_synchronization(monkeypatch):
    ws = FakeSocket([json.dumps({"e": "serverShutdown"})])
    _, statuses, _, _ = setup(monkeypatch, ws, [105])
    assert run() == 2
    assert "serverShutdown" in statuses[-1][1]


def test_depth_staleness_is_not_masked_by_trades(monkeypatch):
    class TradeOnlyAfterBridge(FakeSocket):
        async def __anext__(self):
            if self.messages.empty():
                await asyncio.sleep(.001)
                return trade()
            return await super().__anext__()

    ws = TradeOnlyAfterBridge([depth(99, 100), depth(106, 107)])
    writes, statuses, _, _ = setup(monkeypatch, ws, [105])
    collector.validate_config("unused")["exchange"]["market_data"]["stale_l2_ms"] = 10
    assert asyncio.run(collector.run_stream_async("unused", max_events=100000)) == 2
    assert any(e["event_type"] == "trade" for e in writes)
    assert statuses[-1][0] == "RESYNCING"
    diagnosis = statuses[-1][2]["diagnostics"]
    assert diagnosis["received_depth_events"] == 2
    assert diagnosis["depth_receive_age_ms"] >= 0
    assert diagnosis["depth_applied_age_ms"] >= 0
    assert diagnosis["queue_high_water"] >= 1


def test_pipeline_records_validation_and_io_delays(monkeypatch, tmp_path):
    import time
    original_write = collector.write_event
    ws = FakeSocket([depth(99, 100), depth(106, 107), trade()])
    _, _, _, _ = setup(monkeypatch, ws, [105])
    config = collector.validate_config("unused")
    config["storage"] = {"raw_path": str(tmp_path)}
    def slow_validation(*args):
        time.sleep(.08)
    monkeypatch.setattr(collector, "validate_json", slow_validation)
    monkeypatch.setattr(collector, "append_jsonl", lambda *args: None)
    monkeypatch.setattr(collector, "write_event", original_write)
    assert run() == 0
    metrics = config["_pipeline_metrics"]
    assert metrics["max_validation_ms"] >= 60
    assert metrics["max_write_ms"] >= metrics["max_validation_ms"]
    assert metrics["max_io_ms"] >= 0

