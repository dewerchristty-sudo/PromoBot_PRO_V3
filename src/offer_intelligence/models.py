from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal


INTELLIGENCE_STATES = {
    "UNKNOWN",
    "INSUFFICIENT_HISTORY",
    "BUILDING_HISTORY",
    "STABLE",
    "HIGH_CONFIDENCE",
    "LOW_CONFIDENCE",
    "RARE_PRICE",
    "COMMON_PRICE",
}


@dataclass(frozen=True, slots=True)
class TrendResult:
    direction: str = "UNKNOWN"
    slope_per_observation: Decimal | None = None
    change_percent: Decimal | None = None


@dataclass(frozen=True, slots=True)
class VolatilityResult:
    standard_deviation: Decimal | None = None
    coefficient_percent: Decimal | None = None
    stability_percent: Decimal | None = None


@dataclass(frozen=True, slots=True)
class ConfidenceResult:
    index: Decimal = Decimal("0.00")
    state: str = "LOW_CONFIDENCE"


@dataclass(frozen=True, slots=True)
class RarityResult:
    index: Decimal | None = None
    percentile: Decimal | None = None
    state: str = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class OfferIntelligence:
    product_key: str
    store: str = ""
    title: str = ""
    observation_count: int = 0
    distinct_days: int = 0
    first_observed_at: datetime | None = None
    last_observed_at: datetime | None = None
    current_price: Decimal | None = None
    minimum_price: Decimal | None = None
    maximum_price: Decimal | None = None
    average_price: Decimal | None = None
    median_price: Decimal | None = None
    volatility_percent: Decimal | None = None
    trend: str = "UNKNOWN"
    trend_change_percent: Decimal | None = None
    reduction_frequency_percent: Decimal | None = None
    increase_frequency_percent: Decimal | None = None
    time_since_last_drop_seconds: int | None = None
    time_since_minimum_seconds: int | None = None
    distance_to_minimum_percent: Decimal | None = None
    distance_to_average_percent: Decimal | None = None
    stability_percent: Decimal | None = None
    confidence_index: Decimal = Decimal("0.00")
    rarity_index: Decimal | None = None
    rarity_percentile: Decimal | None = None
    state: str = "UNKNOWN"
    states: tuple[str, ...] = field(default_factory=lambda: ("UNKNOWN",))
    generated_at: datetime | None = None
    operational_effect: str = "NONE"

    def as_dict(self):
        return asdict(self)
