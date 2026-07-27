from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


MATURITY_STATES = {
    "NO_HISTORY", "INSUFFICIENT_HISTORY", "BUILDING_HISTORY",
    "SUFFICIENT_HISTORY", "STABLE_HISTORY", "ANOMALOUS_HISTORY",
}


@dataclass(frozen=True, slots=True)
class RealPriceObservation:
    product_key: str
    store: str
    canonical_identity: str
    canonical_product_id: str
    canonical_url: str
    title: str
    price: Decimal
    currency: str
    observed_at: datetime
    source: str
    run_id: str
    original_url: str
    image_url: str = ""
    availability: str = ""


@dataclass(frozen=True, slots=True)
class ObservationDecision:
    accepted: bool
    stored: bool
    status: str
    reason: str
    observation_hash: str
    product_key: str
    price: Decimal | None
    dry_run: bool


@dataclass(frozen=True, slots=True)
class PriceHistoryAnalysis:
    product_key: str
    store: str
    title: str
    valid_observations: int
    ignored_observations: int
    distinct_days: int
    first_price: Decimal | None
    last_price: Decimal | None
    minimum: Decimal | None
    maximum: Decimal | None
    average: Decimal | None
    median: Decimal | None
    variation_from_previous_percent: Decimal | None
    variation_from_average_percent: Decimal | None
    variation_from_minimum_percent: Decimal | None
    maturity: str
    confidence: Decimal
    real_drop_confirmed: bool
    next_requirement: str
    score_signals: dict = field(default_factory=dict)
