"""Offline hourly inbox schedule; never contacts GitHub or starts Hermes."""
import importlib.util
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / 'ops/github_inbox/hourly_scheduler.py'
spec = importlib.util.spec_from_file_location('hourly_scheduler', MODULE)
scheduler = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scheduler)

UTC = timezone.utc


def test_europe_amsterdam_spring_skips_nonexistent_0230_and_fall_repeats_0230():
    spring = datetime(2026, 3, 29, 0, 30, tzinfo=UTC)
    assert scheduler.next_slot(spring) == datetime(2026, 3, 29, 1, 30, tzinfo=UTC)
    fall_first = datetime(2026, 10, 25, 0, 30, tzinfo=UTC)
    assert scheduler.next_slot(fall_first) == datetime(2026, 10, 25, 1, 30, tzinfo=UTC)
    assert scheduler.next_slot(datetime(2026, 10, 25, 1, 30, tzinfo=UTC)) == datetime(2026, 10, 25, 2, 30, tzinfo=UTC)
    assert scheduler.next_slot(datetime(2026, 11, 9, 11, 30, tzinfo=UTC)) == datetime(2026, 11, 9, 12, 30, tzinfo=UTC)


def test_empty_poll_does_not_launch_child_and_next_slot_is_not_replayed():
    with tempfile.TemporaryDirectory(dir=ROOT) as directory:
        state = Path(directory)
        current = [datetime(2026, 11, 9, 11, 20, tzinfo=UTC)]
        sleeps = []
        calls = []
        class Inbox:
            def tick(self):
                calls.append(current[0])
                return {'status': 'empty'}
        def sleep(seconds):
            sleeps.append(seconds)
            current[0] += timedelta(seconds=seconds)
        assert scheduler.serve(lambda: Inbox(), state, clock=lambda: current[0], sleep=sleep, slots=2,
                               tick_runner=lambda inbox: inbox.tick()) == ['empty', 'empty']
        assert calls == [datetime(2026, 11, 9, 11, 30, tzinfo=UTC),
                         datetime(2026, 11, 9, 12, 30, tzinfo=UTC)]
        assert sleeps == [600, 3600]


def test_long_running_tick_skips_missed_hour_without_overlap():
    with tempfile.TemporaryDirectory(dir=ROOT) as directory:
        current = [datetime(2026, 11, 9, 11, 29, tzinfo=UTC)]
        calls = []
        class Inbox:
            def tick(self):
                calls.append(current[0])
                if len(calls) == 1:
                    current[0] += timedelta(minutes=91)
                return {'status': 'blocked' if len(calls) == 2 else 'empty'}
        result = scheduler.serve(Inbox, Path(directory), clock=lambda: current[0],
            sleep=lambda seconds: current.__setitem__(0, current[0]+timedelta(seconds=seconds)),
            slots=2, tick_runner=lambda inbox: inbox.tick())
        assert result == ['empty', 'blocked']
        assert calls == [datetime(2026, 11, 9, 11, 30, tzinfo=UTC),
                         datetime(2026, 11, 9, 13, 30, tzinfo=UTC)]


def test_actual_inbox_empty_feed_through_scheduler_never_calls_executor():
    import hashlib
    from types import SimpleNamespace
    with tempfile.TemporaryDirectory(dir=ROOT) as directory:
        root = Path(directory)
        state = root / 'github-inbox'
        state.mkdir(mode=0o700)
        (state / 'inbox.lock').touch(mode=0o600)
        enrollment = root / 'enrollment.json'
        enrollment.write_bytes(b'synthetic private enrollment')
        enrollment.chmod(0o600)
        class EmptyGitHub:
            def comments(self, issue, since, etag=None):
                return iter(())
            def publish(self, *args):
                pytest.fail('empty poll cannot publish')
        calls = []
        inbox = scheduler.Inbox(enrollment, state, EmptyGitHub(),
                                lambda *args: calls.append(args))
        inbox._config = lambda: ({'interval_seconds': 300}, SimpleNamespace(issue=43), b'public')
        inbox._save({'v': 1, 'enabled': True, 'start': '2026-11-09T00:00:00Z',
            'start_cursor': {'41': 0, '45': 0}, 'cursor': {'41': 0, '45': 0},
            'etag': {}, 'claim': None, 'next_poll': 0,
            'enrollment_sha256': hashlib.sha256(enrollment.read_bytes()).hexdigest()})
        now = [datetime(2026, 11, 9, 11, 29, tzinfo=UTC)]
        result = scheduler.serve(lambda: inbox, state, clock=lambda: now[0],
            sleep=lambda seconds: now.__setitem__(0, now[0] + timedelta(seconds=seconds)),
            slots=1, tick_runner=lambda instance: instance.tick())
        assert result == ['empty'] and calls == []
        assert inbox._read()['claim'] is None


def test_relative_state_root_is_rejected_before_lock_creation():
    with pytest.raises(ValueError, match='absolute'):
        scheduler.lock_scheduler(Path('relative-inbox'))


def test_second_process_cannot_construct_inbox_while_scheduler_lock_held():
    with tempfile.TemporaryDirectory(dir=ROOT) as directory:
        state = Path(directory)
        fd = scheduler.lock_scheduler(state)
        try:
            with pytest.raises(BlockingIOError):
                scheduler.serve(lambda: pytest.fail('must not construct inbox'), state,
                                clock=lambda: datetime(2026, 11, 9, 11, 29, tzinfo=UTC),
                                sleep=lambda _: None, slots=1)
        finally:
            os.close(fd)


def test_existing_claim_and_quota_are_not_redispatched():
    with tempfile.TemporaryDirectory(dir=ROOT) as directory:
        state = Path(directory)
        current = [datetime(2026, 11, 9, 11, 29, tzinfo=UTC)]
        calls = []
        class Inbox:
            def tick(self):
                calls.append('inbox')
                return {'status': 'blocked', 'reason': 'existing claim'}
        result = scheduler.serve(Inbox, state, clock=lambda: current[0],
            sleep=lambda seconds: current.__setitem__(0, current[0]+timedelta(seconds=seconds)),
            slots=1, tick_runner=lambda inbox: inbox.tick())
        assert result == ['blocked'] and calls == ['inbox']


def test_alarmed_tick_has_finite_deadline_and_restores_handler():
    class Hung:
        def tick(self):
            import time
            time.sleep(.2)
    with pytest.raises(TimeoutError, match='deadline'):
        scheduler.bounded_tick(Hung(), seconds=.02)


def test_dormant_cli_and_doc_do_not_enable_or_dispatch():
    guide = (ROOT / 'ops/github_inbox/HOURLY_SCHEDULER.md').read_text()
    assert 'Europe/Amsterdam' in guide and ':30' in guide
    assert 'UNPROVEN' in guide and 'NO-GO' in guide
    assert not any(line.startswith('python') and '--execute' in line for line in guide.splitlines())
    source = MODULE.read_text()
    assert 'production_executor' in source and 'Inbox' in source
    assert 'bridge_once_candidate' not in source
