#!/usr/bin/env python3
"""Dormant, non-LLM hourly driver for the existing issue-scoped inbox.

Install/enable only after a separate operator approval in an isolated persistent
worker. A claim is owned by Inbox and Bridge, never by this scheduler.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import fcntl
import os
from pathlib import Path
import signal
import stat
import sys
import time
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'autonomous-development')]
from github_inbox import GitHub, Inbox, production_executor  # noqa: E402
from queue_store import _trusted_ancestors  # noqa: E402

UTC = timezone.utc
ZONE = ZoneInfo('Europe/Amsterdam')
TICK_DEADLINE = 3300  # 55 minutes, leaving time before the next wall-hour slot.
LATE_WINDOW = timedelta(minutes=5)


def next_slot(now):
    """Next real local :30 instant; spring gap skips, autumn fold runs twice."""
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('aware clock required')
    instant = now.astimezone(UTC)
    local = instant.astimezone(ZONE).replace(tzinfo=None, minute=0, second=0, microsecond=0)
    candidates = set()
    for hour in range(73):
        wall = local + timedelta(hours=hour, minutes=30)
        for fold in (0, 1):
            possible = wall.replace(tzinfo=ZONE, fold=fold).astimezone(UTC)
            if (possible > instant and
                    possible.astimezone(ZONE).replace(tzinfo=None) == wall):
                candidates.add(possible)
    if not candidates:
        raise RuntimeError('hourly timezone slot unavailable')
    return min(candidates)


def lock_scheduler(root):
    """Second process cannot poll or construct its GitHub client."""
    root = Path(root)
    if not root.is_absolute() or '..' in root.parts:
        raise ValueError('absolute canonical scheduler state required')
    _trusted_ancestors(root)
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise PermissionError('existing private inbox enrollment required')
    lock = root / 'scheduler.lock'
    fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        info, named = os.fstat(fd), lock.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or
                info.st_mode & 0o077 or info.st_nlink != 1 or
                (info.st_dev, info.st_ino) != (named.st_dev, named.st_ino)):
            raise PermissionError('scheduler lock not private')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        parent = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
        return fd
    except BaseException:
        os.close(fd)
        raise


def bounded_tick(inbox, *, seconds=TICK_DEADLINE):
    """Signal deadline leaves Inbox's fsynced claim to block uncertain work."""
    if not 0 < seconds <= TICK_DEADLINE or signal.getitimer(signal.ITIMER_REAL)[0]:
        raise ValueError('tick deadline unavailable')
    def expired(signum, frame):
        raise TimeoutError('inbox tick deadline')
    previous = signal.signal(signal.SIGALRM, expired)
    try:
        signal.setitimer(signal.ITIMER_REAL, seconds)
        return inbox.tick()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def serve(inbox_factory, state_root, *, clock=lambda: datetime.now(UTC),
          sleep=time.sleep, slots=None, tick_runner=bounded_tick):
    """One synchronous consumer; skipped slots never queue catch-up children."""
    fd = lock_scheduler(state_root)
    outcomes = []
    try:
        inbox = inbox_factory()
        while slots is None or len(outcomes) < slots:
            slot = next_slot(clock())
            while True:
                current = clock().astimezone(UTC)
                remaining = (slot - current).total_seconds()
                if remaining > 0:
                    sleep(remaining)
                    continue
                if current - slot > LATE_WINDOW:
                    break  # Clock jump / late wake: skip; never replay a missed slot.
                result = tick_runner(inbox)
                if not isinstance(result, dict) or result.get('status') not in (
                    'empty', 'waiting', 'disabled', 'blocked', 'rate-limited', 'review-ready'):
                    raise ValueError('inbox result unknown; stop for reconciliation')
                if slots is not None:
                    outcomes.append(result['status'])
                break
        return outcomes
    finally:
        os.close(fd)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Dormant hourly :30 Europe/Amsterdam inbox driver')
    parser.add_argument('--enrollment', type=Path, required=True)
    parser.add_argument('--state', type=Path, required=True)
    args = parser.parse_args(argv)
    def factory():
        return Inbox(args.enrollment, args.state, GitHub(), production_executor)
    # Deliberately no --enable, --enroll, --reset or direct Bridge path.
    serve(factory, args.state)


if __name__ == '__main__':
    main()
