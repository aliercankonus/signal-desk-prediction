from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any

from signal_desk.schemas.validate import validate_json


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class AlarmRuleResult:
    level: str
    code: str
    action: str
    message: str


def build_alarm(level: str, code: str, action: str, message: str, *, source: str = "alarm_manager") -> dict[str, Any]:
    base = {"severity": level, "level": level, "code": code, "action": action, "message": message, "source": source, "ts": utc_now_iso()}
    alarm_id = "alm_" + hashlib.sha256(json.dumps(base, sort_keys=True).encode()).hexdigest()[:20]
    payload = {"alarm_id": alarm_id, **base}
    validate_json(payload, "alarm_event.schema.json")
    return payload


def evaluate_system_alarms(config: dict, metrics: dict[str, Any]) -> list[dict[str, Any]]:
    alarms: list[dict[str, Any]] = []
    disk_pct = metrics.get("disk_pct")
    if disk_pct is not None:
        if disk_pct >= config["alarms"]["disk_halt_pct"]:
            alarms.append(build_alarm("HALT", "DISK_HALT", "HALT_ALL_NEW_WORK", f"disk_pct={disk_pct}"))
        elif disk_pct >= config["alarms"]["disk_enter_block_pct"]:
            alarms.append(build_alarm("BLOCK", "DISK_ENTER_BLOCK", "BLOCK_ENTER", f"disk_pct={disk_pct}"))
        elif disk_pct >= config["alarms"]["disk_warn_pct"]:
            alarms.append(build_alarm("WARN", "DISK_WARN", "WARN_ONLY", f"disk_pct={disk_pct}"))
    ram_pct = metrics.get("ram_pct")
    if ram_pct is not None:
        if ram_pct >= config["alarms"]["ram_halt_pct"]:
            alarms.append(build_alarm("HALT", "RAM_HALT", "HALT_ALL_NEW_WORK", f"ram_pct={ram_pct}"))
        elif ram_pct >= config["alarms"]["ram_warn_pct"]:
            alarms.append(build_alarm("WARN", "RAM_WARN", "WARN_ONLY", f"ram_pct={ram_pct}"))
    if metrics.get("l2_stale"):
        alarms.append(build_alarm("BLOCK", "L2_STALE", "BLOCK_ENTER", "L2 market data is stale"))
    if metrics.get("ledger_write_error"):
        alarms.append(build_alarm("HALT", "LEDGER_WRITE_ERROR", "BLOCK_ALL_ORDER_INTENTS", "ledger write failed"))
    return alarms
