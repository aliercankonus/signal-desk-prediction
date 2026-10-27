from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class DecisionInput:
    has_position: bool
    data_stale: bool
    risk_can_enter: bool
    signal_enter: bool
    signal_exit: bool
    config_version: str
    risk_state_id: str
    strategy_id: str | None = None
    prediction_id: str | None = None


def stable_decision_id(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return "dec_" + hashlib.sha256(raw).hexdigest()[:24]


class DecisionEngine:
    def decide(self, inp: DecisionInput) -> dict:
        reasons: list[str] = []
        blocked: list[str] = []
        if inp.data_stale:
            blocked.append("DATA_STALE")
        if not inp.risk_can_enter and not inp.has_position:
            blocked.append("RISK_BLOCK_ENTER")
        if blocked:
            decision = "BLOCK"
            reasons.extend(blocked)
        elif inp.has_position and inp.signal_exit:
            decision = "EXIT"
            reasons.append("EXIT_SIGNAL")
        elif inp.has_position:
            decision = "HOLD"
            reasons.append("POSITION_OPEN")
        elif inp.signal_enter and inp.risk_can_enter:
            decision = "ENTER"
            reasons.append("ENTER_SIGNAL")
        else:
            decision = "WAIT"
            reasons.append("NO_VALID_SIGNAL")

        base = {
            "asof_ts": utc_now_iso(),
            "decision": decision,
            "reason_codes": reasons,
            "blocked_by": blocked,
            "risk_state_id": inp.risk_state_id,
            "prediction_id": inp.prediction_id,
            "strategy_id": inp.strategy_id,
            "config_version": inp.config_version,
        }
        base["decision_id"] = stable_decision_id({k: v for k, v in base.items() if k != "asof_ts"})
        base.update({
            "position_state": "OPEN" if inp.has_position else "FLAT",
            "order_intent_state": None,
            "decision_latency_ms": None,
            "market_data_age_ms": None,
            "cost_gate_result": None,
            "valid_until": None,
            "telemetry": {},
        })
        return base
