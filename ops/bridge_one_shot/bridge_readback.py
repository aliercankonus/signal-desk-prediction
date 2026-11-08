#!/usr/bin/env python3
"""Worker-only, read-only Bridge remote reconciliation after the single claim."""
import argparse
import json
from pathlib import Path
import re
import sys

RUNNER = Path('/workspace/runner')
QUEUE = Path('/state/queue')
AUTH = Path('/private/auth/authorization.json')
PIN = 'e84021a786004456a12de9e25eae50d191da6cf1'
REPO = 'aliercankonus/signal-desk-prediction'


def summarize(row):
    from signal_desk.task_bridge.bridge import verified_pr_receipt
    pr = row.get('observed_pr') or {}
    head, url = row.get('head'), row.get('pr_url')
    expected = (isinstance(head, str) and re.fullmatch(r'[0-9a-f]{40}', head) and
                isinstance(url, str) and
                re.fullmatch(r'https://github\.com/aliercankonus/signal-desk-prediction/pull/[1-9][0-9]*', url))
    verified = bool(expected and row.get('base') == PIN and row.get('status') == 'blocked' and
                    'reason' not in row and row.get('result_mismatch') == [] and
                    row.get('publication_consistent') is True and
                    row.get('publication_inspection_unavailable') is not True and
                    row.get('pr_creation_inspection_unavailable') is not True and
                    verified_pr_receipt(row.get('pr_creation'), head, url) and
                    pr.get('head') == head and pr.get('url') == url and
                    pr.get('ci') in ('success', 'failure', 'pending', 'unknown') and
                    isinstance(pr.get('target_tip'), str) and
                    re.fullmatch(r'[0-9a-f]{40}', pr['target_tip']))
    return {'verified': verified, 'head': head if expected else None,
            'pr_url': url if expected else None, 'observed_ci': pr.get('ci') if verified else None,
            'run_id': row.get('run_id') if isinstance(row.get('run_id'), str) else None}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--queue-id', required=True)
    args = parser.parse_args()
    if not re.fullmatch('[0-9a-f]{32}', args.queue_id):
        parser.error('invalid exact queue identity')
    sys.path.insert(0, str(RUNNER / 'src'))
    from signal_desk.task_bridge.bridge import Bridge, load_authorization
    from signal_desk.task_bridge.adapters import GitHubREST
    policy = load_authorization(AUTH)
    if policy.repo != REPO or policy.issue != 43 or policy.base != PIN:
        raise ValueError('private Bridge policy outside frozen scope')
    result = Bridge(QUEUE / args.queue_id / 'bridge', policy,
                    GitHubREST(policy), None, auth_path=AUTH).reconcile()
    print(json.dumps(summarize(result), sort_keys=True))


if __name__ == '__main__':
    main()
