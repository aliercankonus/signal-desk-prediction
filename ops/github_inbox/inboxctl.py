#!/usr/bin/env python3
"""Dormant inbox control; operator enrollment/enable are separate actions."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'autonomous-development')]
from github_inbox import GitHub, Inbox, production_executor  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('enroll', 'enable', 'tick', 'doctor', 'disable'))
    parser.add_argument('--enrollment', required=True, type=Path)
    parser.add_argument('--state', required=True, type=Path)
    parser.add_argument('--start', help='explicit UTC cursor timestamp, required for enroll')
    args = parser.parse_args()
    if (args.action == 'enroll') != bool(args.start):
        parser.error('--start is required only for enroll')
    # No GitHub credential or network lookup on doctor/disable/enable.
    github = GitHub() if args.action in ('enroll', 'tick') else None
    inbox = Inbox(args.enrollment, args.state, github, production_executor)
    if args.action == 'enroll':
        inbox.enroll(args.start)
        result = inbox.doctor()
    elif args.action == 'doctor':
        result = inbox.doctor()
    elif args.action == 'disable':
        inbox.disable()
        result = inbox.doctor()
    elif args.action == 'enable':
        inbox.enable()
        result = inbox.doctor()
    else:
        result = inbox.tick()
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
