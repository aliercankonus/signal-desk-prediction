from signal_desk.alarms.manager import evaluate_system_alarms


def test_disk_halt_alarm_precedence():
    config = {"alarms": {"disk_warn_pct": 70, "disk_enter_block_pct": 85, "disk_halt_pct": 95, "ram_warn_pct": 80, "ram_halt_pct": 95}}
    alarms = evaluate_system_alarms(config, {"disk_pct": 96, "ram_pct": 50})
    assert alarms[0]["level"] == "HALT"
    assert alarms[0]["action"] == "HALT_ALL_NEW_WORK"


def test_l2_stale_blocks_enter():
    config = {"alarms": {"disk_warn_pct": 70, "disk_enter_block_pct": 85, "disk_halt_pct": 95, "ram_warn_pct": 80, "ram_halt_pct": 95}}
    alarms = evaluate_system_alarms(config, {"l2_stale": True})
    assert alarms[0]["level"] == "BLOCK"
    assert alarms[0]["code"] == "L2_STALE"
