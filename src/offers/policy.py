from dataclasses import dataclass, field
from typing import Mapping, Sequence


@dataclass(frozen=True, slots=True)
class OfferScorePolicy:
    """Política versionada; pesos e faixas ficam centralizados aqui."""

    policy_version: int = 2
    discount_bands: Sequence[tuple[float, float]] = (
        (50.0, 35.0),
        (40.0, 30.0),
        (30.0, 25.0),
        (20.0, 15.0),
        (10.0, 5.0),
        (0.0, 0.0),
    )
    historical_low_points: float = 20.0
    historical_near_low_points: float = 10.0
    historical_near_low_percent: float = 5.0
    minimum_reliable_samples: int = 3
    seller_reputation_points: Mapping[str, float] = field(default_factory=lambda: {
        "excelente": 10.0,
        "muito boa": 7.0,
        "boa": 4.0,
    })
    official_store_points: float = 10.0
    trusted_store_points: float = 7.0
    category_demand_points: Mapping[str, float] = field(default_factory=lambda: {
        "muito alta": 10.0,
        "alta": 7.0,
        "media": 4.0,
        "média": 4.0,
    })
    coupon_points: float = 5.0
    free_shipping_points: float = 5.0
    cashback_points: float = 3.0
    maximum_confidence_points: float = 7.0
    valid_price_points: float = 3.0
    image_points: float = 1.0
    original_link_points: float = 1.0
    title_good_points: float = 3.0
    title_acceptable_points: float = 1.0
    rating_points: float = 3.0
    sales_points: float = 5.0
    availability_points: float = 4.0
    category_known_points: float = 2.0
    falling_trend_points: float = 3.0
    new_record_points: float = 2.0
    no_discount_no_history_cap: float = 39.0
    partial_evidence_cap: float = 74.0
    exceptional_confidence_minimum: float = 75.0
    suspicious_discount_percent: float = 90.0
    classifications: Sequence[tuple[float, str]] = (
        (90.0, "oferta_excepcional"),
        (75.0, "oferta_muito_boa"),
        (60.0, "oferta_boa"),
        (40.0, "oferta_regular"),
        (0.0, "oferta_fraca_sem_evidencia"),
    )
    minimum_total: float = 0.0
    maximum_total: float = 100.0

    def points_for_discount(self, discount: float) -> float:
        value = max(float(discount or 0), 0.0)
        for minimum, points in self.discount_bands:
            if value >= minimum:
                return float(points)
        return 0.0

    def classify(self, total: float) -> str:
        value = max(float(total or 0), 0.0)
        for minimum, classification in self.classifications:
            if value >= minimum:
                return classification
        return "oferta_fraca_sem_evidencia"


@dataclass(frozen=True, slots=True)
class OfferAnalysisPolicy:
    duplicate_window_hours: float = 24.0
    significant_price_drop_percent: float = 5.0
    history_minimum_samples: int = 3
    history_window_days: int = 90
    history_near_low_percent: float = 5.0
    ranking_max_per_category: int = 1
    ranking_max_per_store: int = 2
    ranking_max_per_identity: int = 1
    ranking_allow_repetition_if_needed: bool = True
    same_price_tolerance_percent: float = 1.0


@dataclass(frozen=True, slots=True)
class OfferSchedulerPolicy:
    max_per_hour: int = 3
    max_per_day: int = 12
    minimum_interval_minutes: int = 15
    minimum_score: float = 70.0
    excellent_score: float = 90.0
    reservation_minutes: int = 10
    default_expiration_hours: int = 12
    send_medium_offers: bool = False
    start_hour: int = 8
    end_hour: int = 22
    ranking_max_per_category: int = 1
    ranking_max_per_store: int = 2
    ranking_max_per_identity: int = 1
