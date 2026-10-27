import json

import pytest
from jsonschema import SchemaError

from signal_desk.schemas.validate import validate_json, SchemaValidationError


def test_reused_validator_still_rejects_invalid_events(tmp_path):
    schema = tmp_path / "event.json"
    schema.write_text(json.dumps({"type": "object", "required": ["price"]}))
    validate_json({"price": 1}, schema.name, tmp_path)
    with pytest.raises(SchemaValidationError):
        validate_json({}, schema.name, tmp_path)


def test_schema_replacement_invalidates_validator(tmp_path):
    schema = tmp_path / "event.json"
    schema.write_text(json.dumps({"type": "object", "required": ["price"]}))
    validate_json({"price": 1}, schema.name, tmp_path)
    replacement = tmp_path / "replacement.json"
    replacement.write_text(json.dumps({"type": "object", "required": ["amount"]}))
    replacement.replace(schema)
    with pytest.raises(SchemaValidationError):
        validate_json({"price": 1}, schema.name, tmp_path)
    validate_json({"amount": 1}, schema.name, tmp_path)


def test_invalid_schema_is_never_cached_as_valid(tmp_path):
    schema = tmp_path / "event.json"
    schema.write_text('{"type":"not-a-json-schema-type"}')
    with pytest.raises(SchemaError):
        validate_json({}, schema.name, tmp_path)

