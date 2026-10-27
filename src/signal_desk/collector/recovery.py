"""Bounded recovery policy; continuous collection remains opt-in."""
from dataclasses import dataclass, asdict, fields
import math


@dataclass(frozen=True)
class RecoveryPolicy:
    max_failures: int = 5
    retry_initial_seconds: float = 1.0
    retry_max_seconds: float = 30.0
    stable_reset_seconds: float = 60.0
    status_interval_seconds: float = 5.0
    storage_check_seconds: float = 5.0
    snapshot_timeout_seconds: float = 15.0

    @classmethod
    def from_config(cls, config):
        supplied = config.get("collector", {})
        known = {f.name for f in fields(cls)}
        if not isinstance(supplied, dict) or set(supplied) - known:
            raise ValueError("Unknown or invalid collector recovery settings")
        policy = cls(**supplied)
        for name, value in asdict(policy).items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"collector.{name} must be finite and positive")
        if not isinstance(policy.max_failures, int) or not 1 <= policy.max_failures <= 20:
            raise ValueError("collector.max_failures must be an integer in [1,20]")
        if policy.retry_initial_seconds < 1 or policy.retry_max_seconds < policy.retry_initial_seconds:
            raise ValueError("collector retry bounds are invalid")
        return policy

    def delay(self, failures):
        return min(self.retry_max_seconds, self.retry_initial_seconds * 2 ** (failures - 1))

