from dataclasses import dataclass
from datetime import time
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


def parse_times(value):
    result = []
    for item in str(value or "").split(","):
        item = item.strip()
        if not item:
            continue
        hour, minute = item.split(":", 1)
        result.append(time(int(hour), int(minute)))
    return tuple(sorted(set(result)))


@dataclass(frozen=True, slots=True)
class PriceCollectionSchedulerConfig:
    enabled: bool = False
    times: tuple[time, ...] = (
        time(9, 0), time(15, 0), time(21, 0),
    )
    allowed_stores: tuple[str, ...] = ("mercado_livre",)
    max_products_per_run: int = 100
    retry_on_failure: bool = True
    retry_minutes: int = 15
    log_level: str = "INFO"

    @classmethod
    def from_environment(cls):
        load_dotenv(DEFAULT_ENV_PATH, override=False)
        raw_times = os.getenv(
            "PRICE_COLLECTION_TIMES", "09:00,15:00,21:00"
        )
        try:
            times = parse_times(raw_times)
        except (ValueError, TypeError):
            times = ()
        stores = tuple(
            item.strip().casefold() for item in os.getenv(
                "PRICE_COLLECTION_ALLOWED_STORES", "mercado_livre"
            ).split(",") if item.strip()
        )
        return cls(
            enabled=boolean("PRICE_COLLECTION_ENABLED", False),
            times=times,
            allowed_stores=stores,
            max_products_per_run=integer(
                "PRICE_COLLECTION_MAX_PRODUCTS_PER_RUN", 100, 1
            ),
            retry_on_failure=boolean(
                "PRICE_COLLECTION_RETRY_ON_FAILURE", True
            ),
            retry_minutes=integer(
                "PRICE_COLLECTION_RETRY_MINUTES", 15, 1
            ),
            log_level=os.getenv(
                "PRICE_COLLECTION_LOG_LEVEL", "INFO"
            ).strip().upper(),
        )
