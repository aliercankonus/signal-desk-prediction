"""Bounded private self-report checkpoint; Bridge journal/remote state supersede it.

No child or supervisor may infer effect success solely from this file.
"""
from __future__ import annotations
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import uuid

STAGES = ('child-intent', 'pre-tests', 'post-tests', 'pre-commit', 'post-commit',
          'pre-push', 'post-push', 'pushed-head-verified', 'child-completed',
          'pre-pr-publication', 'post-pr-publication', 'paused')
MAX = 4096


def checkpoint(state, identity, stage, *, head=None, remaining='review/reconcile', uncertainty='unknown',
               session=None, test_receipt=None, publication_receipt=None):
    """Fsynced 0600 replacement before an effect; append-only confirmed stage is NOT implied."""
    state = Path(state)
    info = state.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise PermissionError('checkpoint state must be private directory')
    if (stage not in STAGES or not isinstance(identity, dict) or
            set(identity) != {'task_issue', 'authorization_identity', 'runner_commit',
                             'base', 'branch', 'run_id', 'worktree'} or
            not re.fullmatch('[0-9a-f]{64}', identity['authorization_identity']) or
            not re.fullmatch('[0-9a-f]{40}', identity['runner_commit']) or
            not re.fullmatch('[0-9a-f]{40}', identity['base']) or
            not re.fullmatch('[0-9a-f]{32}', identity['run_id']) or
            type(identity['task_issue']) is not int or
            identity['worktree'] != str(state / 'worktrees' / identity['run_id']) or
            not isinstance(identity['branch'], str) or
            not re.fullmatch('[a-z][a-z0-9-]{0,62}', identity['branch']) or
            head is not None and not re.fullmatch('[0-9a-f]{40}', head) or
            not all(isinstance(x, str) and len(x) <= 256 and '\n' not in x
                    for x in (remaining, uncertainty)) or
            any(x is not None and (not isinstance(x, str) or len(x) > 256 or '\n' in x)
                for x in (session, test_receipt, publication_receipt))):
        raise ValueError('checkpoint fields outside bounds')
    lock = os.open(state / 'recovery.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        named = (state / 'recovery.lock').lstat()
        held = os.fstat(lock)
        if (not stat.S_ISREG(held.st_mode) or held.st_uid != os.geteuid() or
                held.st_mode & 0o077 or (held.st_ino, held.st_dev) != (named.st_ino, named.st_dev)):
            raise PermissionError('checkpoint lock unsafe')
        fcntl.flock(lock, fcntl.LOCK_EX)
        target = state / 'recovery-checkpoint.json'
        previous = None
        try:
            fd = os.open(target, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            pass
        else:
            try:
                item = os.fstat(fd)
                if (not stat.S_ISREG(item.st_mode) or item.st_uid != os.geteuid() or
                        item.st_mode & 0o077 or item.st_size > MAX):
                    raise PermissionError('checkpoint must be bounded private regular file')
                previous = json.loads(os.read(fd, MAX + 1))
            finally:
                os.close(fd)
            if previous.get('identity') != identity:
                raise ValueError('checkpoint identity changed; preserve for review')
        confirmed = stage if stage in ('post-tests', 'post-commit', 'post-push',
                                         'pushed-head-verified', 'child-completed') else (
            previous.get('last_confirmed') if previous else 'worktree-created')
        record = {'v': 1, 'identity': identity, 'stage': stage, 'last_confirmed': confirmed,
                  'head': head or (previous.get('head') if previous else None),
                  'session': session or (previous.get('session') if previous else None),
                  'test_receipt': test_receipt or (previous.get('test_receipt') if previous else None),
                  'publication_receipt': publication_receipt or (
                      previous.get('publication_receipt') if previous else None),
                  'remaining': remaining, 'uncertainty': uncertainty,
                  'previous_stage': previous['stage'] if previous else None}
        data = json.dumps(record, sort_keys=True, separators=(',', ':')).encode()
        if len(data) > MAX:
            raise ValueError('checkpoint exceeds bound')
        temporary = state / ('recovery-' + uuid.uuid4().hex)
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, 'wb') as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, target)
            directory = os.open(state, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)
        return record
    finally:
        os.close(lock)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--state', required=True)
    parser.add_argument('--identity', required=True, help='private identity JSON path, not issue text')
    parser.add_argument('--stage', choices=STAGES, required=True)
    parser.add_argument('--head')
    parser.add_argument('--remaining', default='review/reconcile')
    parser.add_argument('--uncertainty', default='unknown')
    parser.add_argument('--session')
    parser.add_argument('--test-receipt')
    parser.add_argument('--publication-receipt')
    args = parser.parse_args()
    path = Path(args.identity)
    if path.is_symlink() or path.stat().st_size > 2048 or path.stat().st_mode & 0o077:
        parser.error('identity file must be bounded and private')
    identity = json.loads(path.read_bytes())
    checkpoint(args.state, identity, args.stage, head=args.head,
               remaining=args.remaining, uncertainty=args.uncertainty,
               session=args.session, test_receipt=args.test_receipt,
               publication_receipt=args.publication_receipt)


if __name__ == '__main__':
    main()
