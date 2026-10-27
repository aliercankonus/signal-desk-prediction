from signal_desk.config.loader import validate_config


def test_example_config_validates():
    cfg = validate_config("config/config.example.yaml", "schemas/config.schema.json")
    assert cfg["exchange"]["name"] == "binance"
    assert cfg["exchange"]["symbol"] == "BTCUSDT"
    assert cfg["project"]["execution_enabled"] is False
    assert cfg["project"]["mode"] == "paper"
