from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
import json


DEFAULT_CONFIG_PATH = Path(os.environ.get("SIGNAL_DESK_CONFIG", "config/config.yaml"))
DEFAULT_CONFIG_SCHEMA_PATH = Path("schemas/config.schema.json")


class ConfigError(RuntimeError):
    pass


def load_yaml(path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"Config root must be an object: {path}")
    return data


def load_json(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ConfigError(f"JSON root must be an object: {path}")
    return data


def validate_config(config_path: str | Path = DEFAULT_CONFIG_PATH, schema_path: str | Path = DEFAULT_CONFIG_SCHEMA_PATH) -> dict[str, Any]:
    config = load_yaml(config_path)
    schema = load_json(schema_path)
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(config), key=lambda e: list(e.path))
    if errors:
        msg = "\n".join(f"{list(e.path)}: {e.message}" for e in errors)
        raise ConfigError(f"Config validation failed:\n{msg}")
    _validate_operational_invariants(config)
    return config


def _validate_operational_invariants(config: dict[str, Any]) -> None:
    project = config.get("project", {})
    exchange = config.get("exchange", {})
    if project.get("execution_enabled") is not False:
        raise ConfigError("V0 must run with execution_enabled=false")
    if project.get("mode") != "paper":
        raise ConfigError("V0 must run in project.mode=paper")
    if exchange.get("name") != "binance" or exchange.get("symbol") != "BTCUSDT" or exchange.get("product_type") != "spot":
        raise ConfigError("V0 is fixed to Binance BTCUSDT spot")
    fees = config.get("fees", {})
    if fees.get("source") == "manual_placeholder_verify_before_run":
        # Allow tests and skeleton, but health status will show BLOCK for ENTER.
        pass
    resources = config.get("resources", {})
    if int(resources.get("ram_total_mb", 0)) > 2048:
        raise ConfigError("V0 resource profile must not assume more than 2GB RAM")
