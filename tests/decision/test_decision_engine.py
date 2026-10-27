from signal_desk.decision.engine import DecisionEngine, DecisionInput
from signal_desk.schemas.validate import validate_json


def test_decision_blocks_stale_data_and_is_idempotent_for_same_inputs():
    engine = DecisionEngine()
    inp = DecisionInput(
        has_position=False,
        data_stale=True,
        risk_can_enter=True,
        signal_enter=True,
        signal_exit=False,
        config_version="cfg-v13-example-001",
        risk_state_id="risk-1",
        strategy_id="S1",
        prediction_id="pred-1",
    )
    d1 = engine.decide(inp)
    d2 = engine.decide(inp)
    validate_json(d1, "decision.schema.json")
    assert d1["decision"] == "BLOCK"
    assert "DATA_STALE" in d1["blocked_by"]
    assert d1["decision_id"] == d2["decision_id"]
