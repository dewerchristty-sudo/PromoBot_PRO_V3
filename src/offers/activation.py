from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path


def _boolean(name, default):
    value = os.getenv(name)
    if value is None:
        return bool(default)
    return value.strip().casefold() in {"1", "true", "yes", "on", "sim"}


def _integer(name, default, minimum=0, maximum=None):
    try:
        value = int(float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        value = int(default)
    value = max(int(minimum), value)
    return min(value, int(maximum)) if maximum is not None else value


def _number(name, default, minimum=0, maximum=None):
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = float(default)
    value = max(float(minimum), value)
    return min(value, float(maximum)) if maximum is not None else value


@dataclass(frozen=True, slots=True)
class OfferActivationFlags:
    intelligent_scheduler_enabled: bool = False
    compare_with_legacy: bool = True
    canary_percent: int = 0
    minimum_score_to_send: float = 85
    max_send_per_hour: int = 3
    max_send_per_day: int = 12
    enable_rollback: bool = True
    dry_run_transport: bool = False
    auto_stop_enabled: bool = True
    max_consecutive_errors: int = 3
    max_rollbacks_per_hour: int = 2
    max_error_rate_percent: float = 10
    max_decision_time_ms: float = 500
    stop_on_duplicate: bool = True
    stop_on_audit_failure: bool = True

    @classmethod
    def from_environment(cls):
        flags = cls(
            intelligent_scheduler_enabled=_boolean(
                "OFFER_INTELLIGENT_SCHEDULER_ENABLED", False
            ),
            compare_with_legacy=_boolean(
                "OFFER_COMPARE_WITH_LEGACY", True
            ),
            canary_percent=_integer(
                "OFFER_CANARY_PERCENT", 0, 0, 100
            ),
            minimum_score_to_send=_number(
                "OFFER_MIN_SCORE_TO_SEND", 85, 0, 100
            ),
            max_send_per_hour=_integer(
                "OFFER_MAX_SEND_PER_HOUR", 3, 0
            ),
            max_send_per_day=_integer(
                "OFFER_MAX_SEND_PER_DAY", 12, 0
            ),
            enable_rollback=_boolean("OFFER_ENABLE_ROLLBACK", True),
            dry_run_transport=_boolean("OFFER_DRY_RUN_TRANSPORT", False),
            auto_stop_enabled=_boolean(
                "OFFER_CANARY_AUTO_STOP_ENABLED", True
            ),
            max_consecutive_errors=_integer(
                "OFFER_CANARY_MAX_CONSECUTIVE_ERRORS", 3, 1
            ),
            max_rollbacks_per_hour=_integer(
                "OFFER_CANARY_MAX_ROLLBACKS_PER_HOUR", 2, 0
            ),
            max_error_rate_percent=_number(
                "OFFER_CANARY_MAX_ERROR_RATE_PERCENT", 10, 0, 100
            ),
            max_decision_time_ms=_number(
                "OFFER_CANARY_MAX_DECISION_TIME_MS", 500, 1
            ),
            stop_on_duplicate=_boolean(
                "OFFER_CANARY_STOP_ON_DUPLICATE", True
            ),
            stop_on_audit_failure=_boolean(
                "OFFER_CANARY_STOP_ON_AUDIT_FAILURE", True
            ),
        )
        path = Path(os.getenv(
            "OFFER_ACTIVATION_CONFIG_PATH", "offer_activation.json"
        ))
        if not path.exists():
            return flags
        try:
            controlled = json.loads(path.read_text(encoding="utf-8"))
            allowed = cls.__dataclass_fields__
            return cls(**{
                **flags.as_dict(),
                **{
                    key: value for key, value in controlled.items()
                    if key in allowed
                },
            })
        except (OSError, ValueError, TypeError):
            return flags

    @property
    def mode(self):
        if not self.intelligent_scheduler_enabled:
            return "legado"
        if self.canary_percent <= 0:
            return "legado_canary_0"
        if self.canary_percent >= 100:
            return "inteligente"
        return "canary"

    def as_dict(self):
        return asdict(self)
