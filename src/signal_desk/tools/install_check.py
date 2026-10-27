"""Installer health verification and local, secret-free deployment manifest."""
import argparse
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform
from urllib.parse import urlparse
from urllib.request import urlopen

from signal_desk.config.loader import validate_config


def check_health(payload):
    if not isinstance(payload, dict) or payload.get("status") != "ok":
        raise ValueError("API health is not ok")
    if payload.get("mode") != "paper" or payload.get("execution_enabled") is not False:
        raise ValueError("API must be paper-only with real execution disabled")
    if payload.get("exchange") != "binance" or payload.get("symbol") != "BTCUSDT":
        raise ValueError("Unexpected exchange or symbol")
    return payload


def build_manifest(config_path, git_commit, project, smoke, api_image, collector_image):
    config = validate_config(config_path)
    return {
        "status": "installation_smoke_passed" if smoke else "installation_tests_passed_smoke_skipped",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_commit, "compose_project": project,
        "api_image": api_image, "collector_image": collector_image,
        "config_version": config["project"]["config_version"],
        "config_sha256": hashlib.sha256(Path(config_path).read_bytes()).hexdigest(),
        "python": platform.python_version(),
        "dependencies": {name: version(name) for name in ("PyYAML", "jsonschema", "requests", "websockets", "pytest")},
        "mode": "paper", "execution_enabled": False,
        "collector_default": "idle", "public_smoke_run": smoke,
        "data_volume": f"{project}_signal_desk_data",
        "limits": "Only installation/tests/optional short smoke; not full trading readiness",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--health-url")
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--git-commit")
    parser.add_argument("--project")
    parser.add_argument("--smoke", type=int, choices=[0, 1], default=1)
    parser.add_argument("--api-image", default="")
    parser.add_argument("--collector-image", default="")
    args = parser.parse_args()
    try:
        if args.health_url:
            address = urlparse(args.health_url)
            if address.scheme != "http" or address.hostname not in {"127.0.0.1", "localhost"}:
                raise ValueError("Installer health endpoint must be loopback HTTP")
            with urlopen(args.health_url, timeout=5) as response:
                result = check_health(json.load(response))
        else:
            if not args.git_commit or not args.project or not args.api_image or not args.collector_image:
                raise ValueError("Manifest requires commit, project and both image IDs")
            result = build_manifest(args.config, args.git_commit, args.project,
                                    bool(args.smoke), args.api_image, args.collector_image)
        print(json.dumps(result, sort_keys=True, indent=2), flush=True)
        return 0
    except Exception as exc:
        print(json.dumps({"status": "error", "reason": str(exc)[:240]}), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

