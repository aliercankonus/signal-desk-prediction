from signal_desk.schemas.validate import validate_all_schemas


def test_all_schema_files_are_valid():
    checked = validate_all_schemas("schemas")
    assert "market_event.schema.json" in checked
    assert "config.schema.json" in checked
