from dataclasses import dataclass
import os

from dotenv import load_dotenv

from src.affiliates.config import DEFAULT_ENV_PATH


def integer(name, default, minimum=0):
    try:
        return max(int(os.getenv(name, str(default))), minimum)
    except ValueError:
        return default


def decimal_value(name, default):
    from decimal import Decimal, InvalidOperation
    try:
        return Decimal(os.getenv(name, str(default)))
    except InvalidOperation:
        return Decimal(str(default))


@dataclass(frozen=True, slots=True)
class PriceHistoryConfig:
    min_observations: int = 5
    min_distinct_days: int = 3
    stable_days: int = 7
    outlier_percent: int = 50
    min_interval_minutes: int = 60
    duplicate_window_minutes: int = 60
    change_min_percent: str = "2"
    change_min_amount: str = "1.00"

    @classmethod
    def from_environment(cls):
        load_dotenv(DEFAULT_ENV_PATH, override=False)
        return cls(
            min_observations=integer(
                "PRICE_HISTORY_MIN_OBSERVATIONS", 5, 2
            ),
            min_distinct_days=integer(
                "PRICE_HISTORY_MIN_DISTINCT_DAYS", 3, 2
            ),
            stable_days=integer("PRICE_HISTORY_STABLE_DAYS", 7, 3),
            outlier_percent=integer(
                "PRICE_HISTORY_OUTLIER_PERCENT", 50, 10
            ),
            min_interval_minutes=integer(
                "PRICE_HISTORY_MIN_INTERVAL_MINUTES", 60, 1
            ),
            duplicate_window_minutes=integer(
                "PRICE_HISTORY_DUPLICATE_WINDOW_MINUTES", 60, 1
            ),
            change_min_percent=str(decimal_value(
                "PRICE_CHANGE_MIN_PERCENT", "2"
            )),
            change_min_amount=str(decimal_value(
                "PRICE_CHANGE_MIN_AMOUNT", "1.00"
            )),
        )
