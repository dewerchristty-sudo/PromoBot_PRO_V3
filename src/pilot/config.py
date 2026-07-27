from dataclasses import dataclass
import os

from dotenv import load_dotenv

from src.affiliates.config import DEFAULT_ENV_PATH


def boolean(name, default):
    value = os.getenv(name)
    if value is None:
        return bool(default)
    return value.strip().casefold() in {"1", "true", "yes", "on", "sim"}


def integer(name, default, minimum=0):
    try:
        return max(int(os.getenv(name, str(default))), minimum)
    except ValueError:
        return default


def number(name, default, minimum=0):
    try:
        return max(float(os.getenv(name, str(default))), minimum)
    except ValueError:
        return float(default)


@dataclass(frozen=True, slots=True)
class PilotConfig:
    enabled: bool = False
    group_id: str = ""
    max_messages: int = 1
    require_manual_confirmation: bool = True
    allowed_stores: tuple[str, ...] = ("Mercado Livre",)
    minimum_score: float = 90.0
    cooldown_minutes: int = 60
    auto_stop_on_error: bool = True
    authorization_timeout_seconds: int = 120

    @classmethod
    def from_environment(cls):
        load_dotenv(DEFAULT_ENV_PATH, override=False)
        stores = tuple(
            value.strip() for value in os.getenv(
                "PILOT_ALLOWED_STORES", "Mercado Livre"
            ).split(",") if value.strip()
        )
        return cls(
            enabled=boolean("PILOT_MODE_ENABLED", False),
            group_id=os.getenv("PILOT_GROUP_ID", "").strip(),
            max_messages=integer("PILOT_MAX_MESSAGES", 1, 1),
            require_manual_confirmation=boolean(
                "PILOT_REQUIRE_MANUAL_CONFIRMATION", True
            ),
            allowed_stores=stores or ("Mercado Livre",),
            minimum_score=number("PILOT_MIN_SCORE", 90, 0),
            cooldown_minutes=integer("PILOT_COOLDOWN_MINUTES", 60, 0),
            auto_stop_on_error=boolean(
                "PILOT_AUTO_STOP_ON_ERROR", True
            ),
            authorization_timeout_seconds=integer(
                "PILOT_AUTHORIZATION_TIMEOUT_SECONDS", 120, 30
            ),
        )
