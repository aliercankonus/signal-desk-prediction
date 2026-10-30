"""Manual operator entry point; no daemon or scheduler."""
import argparse
import json
import subprocess
from pathlib import Path
from .bridge import BASE, DIGEST, ISSUE, REPO, Bridge, Policy, doctor
from .adapters import GitHubREST, HermesAgent


def validate_checkout_paths(source, state):
    if state.is_symlink():
        raise ValueError('state symlink denied')
    source, state = source.resolve(), state.resolve()
    root = subprocess.run(['git', '-C', str(source), 'rev-parse', '--show-toplevel'],
                          capture_output=True, text=True, timeout=10, check=True).stdout.strip()
    if source != Path(root).resolve():
        raise ValueError('source must be the checkout root')
    if state == source or source in state.parents or state in source.parents:
        raise ValueError('state must be outside the git checkout')
    if state.exists() and state.stat().st_mode & 0o077:
        raise ValueError('state must be private (mode 0700)')
    return source, state


def main(argv=None):
    parser = argparse.ArgumentParser(description='One-issue bounded task bridge')
    parser.add_argument('mode', choices=('doctor', 'reconcile', 'once'))
    parser.add_argument('--state', type=Path, required=True, help='private local directory outside the git checkout')
    parser.add_argument('--source', type=Path, help='development git checkout, required by once')
    parser.add_argument('--execute-hermes', action='store_true', help='explicitly allow one real invocation')
    args = parser.parse_args(argv)
    if args.mode == 'doctor':
        print(json.dumps(doctor(args.state)))
        return 0
    if args.mode == 'reconcile':
        try:
            result = Bridge(args.state, Policy(REPO, ISSUE, DIGEST, BASE), GitHubREST(), None).reconcile()
        except Exception:
            parser.exit(1, 'remote inspection unavailable; local journal remains unchanged\n')
        print(json.dumps(result))
        return 0
    if not args.execute_hermes or not args.source:
        parser.error('once requires --source and --execute-hermes')
    try:
        source, state = validate_checkout_paths(args.source, args.state)
    except ValueError as exc:
        parser.error(str(exc))
    except (OSError, subprocess.SubprocessError):
        parser.error('source checkout unavailable')
    try:
        result = Bridge(state, Policy(REPO, ISSUE, DIGEST, BASE), GitHubREST(),
                        HermesAgent(source, state)).once()
    except Exception:
        parser.exit(1, 'bridge blocked; inspect private state with doctor\n')
    print(json.dumps({key: result.get(key) for key in ('status', 'run_id', 'base', 'head', 'pr_url', 'ci')}))
    return 0 if result['status'] == 'review-ready' else 1


if __name__ == '__main__':
    raise SystemExit(main())
