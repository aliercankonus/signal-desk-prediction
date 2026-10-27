from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from jsonschema import Draft202012Validator


class SchemaValidationError(RuntimeError):
    pass


def load_schema(schema_name: str, schema_dir: str | Path = "schemas") -> dict[str, Any]:
    path = Path(schema_dir) / schema_name
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    Draft202012Validator.check_schema(data)
    return data


def validate_json(instance: dict[str, Any], schema_name: str, schema_dir: str | Path = "schemas") -> None:
    schema = load_schema(schema_name, schema_dir)
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
    if errors:
        msg = "\n".join(f"{list(e.path)}: {e.message}" for e in errors)
        raise SchemaValidationError(f"{schema_name} validation failed:\n{msg}")


def validate_all_schemas(schema_dir: str | Path = "schemas") -> list[str]:
    paths = sorted(Path(schema_dir).glob("*.schema.json"))
    checked = []
    for path in paths:
        with path.open("r", encoding="utf-8") as f:
            Draft202012Validator.check_schema(json.load(f))
        checked.append(path.name)
    return checked
