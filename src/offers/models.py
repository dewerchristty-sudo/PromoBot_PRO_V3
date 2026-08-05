from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Optional


@dataclass(slots=True)
class OfferCandidate:
    """Representação normalizada e tolerante a dados incompletos."""

    product_id: Optional[Any] = None
    product_code: str = ""
    title: str = ""
    store: str = ""
    brand: str = ""
    model: str = ""
    color: str = ""
    current_price: Optional[float] = None
    previous_price: Optional[float] = None
    historical_reference_price: Optional[float] = None
    historical_minimum: Optional[float] = None
    historical_percentile: Optional[float] = None
    price_sample_count: int = 0
    seller_name: str = ""
    seller_reputation: str = ""
    official_store: bool = False
    trusted_store: bool = False
    category: str = ""
    category_demand: str = ""
    has_coupon: bool = False
    free_shipping: bool = False
    cashback: bool = False
    rating: Optional[float] = None
    review_count: int = 0
    sold_count: int = 0
    stock_available: Optional[bool] = None
    availability: str = ""
    image_url: str = ""
    affiliate_link: str = ""
    product_link: str = ""
    collected_at: Optional[datetime] = None
    previous_price_validated: bool = False
    duplicate: bool = False
    future_signals: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, product: Mapping[str, Any]) -> "OfferCandidate":
        """Cria um candidato sem exigir mudanças nos scrapers atuais."""

        return cls(
            product_id=product.get("product_id", product.get("id")),
            product_code=str(product.get("product_code", "") or ""),
            title=str(product.get("title", product.get("titulo", "")) or ""),
            store=str(product.get("store", product.get("loja", "")) or ""),
            brand=str(product.get("brand", product.get("marca", "")) or ""),
            model=str(product.get("model", product.get("modelo", "")) or ""),
            color=str(product.get("color", product.get("cor", "")) or ""),
            current_price=product.get(
                "current_price",
                product.get("preco_valor", product.get("preco")),
            ),
            previous_price=(
                product.get("previous_price")
                or product.get("preco_anterior")
                or product.get("preco_antigo")
            ),
            historical_reference_price=product.get(
                "historical_reference_price",
                product.get("maior_preco"),
            ),
            historical_minimum=product.get(
                "historical_minimum",
                product.get("menor_historico"),
            ),
            historical_percentile=product.get("historical_percentile"),
            price_sample_count=int(product.get(
                "price_sample_count",
                product.get("coletas", 0),
            ) or 0),
            seller_name=str(product.get("seller_name", "") or ""),
            seller_reputation=str(product.get("seller_reputation", "") or ""),
            official_store=bool(product.get("official_store", False)),
            trusted_store=bool(product.get("trusted_store", False)),
            category=str(
                product.get("category", product.get("categoria_manual", ""))
                or ""
            ),
            category_demand=str(product.get("category_demand", "") or ""),
            has_coupon=bool(product.get("has_coupon", False)),
            free_shipping=bool(product.get("free_shipping", False)),
            cashback=bool(product.get("cashback", False)),
            rating=product.get("rating", product.get("avaliacao")),
            review_count=int(product.get(
                "review_count", product.get("quantidade_avaliacoes", 0)
            ) or 0),
            sold_count=int(product.get(
                "sold_count", product.get("quantidade_vendas", 0)
            ) or 0),
            stock_available=product.get(
                "stock_available", product.get("em_estoque")
            ),
            availability=str(product.get("availability", "") or ""),
            image_url=str(
                product.get("image_url", product.get("imagem", "")) or ""
            ),
            affiliate_link=str(product.get("affiliate_link", "") or ""),
            product_link=str(
                product.get("product_link", product.get("link", "")) or ""
            ),
            collected_at=product.get("collected_at"),
            previous_price_validated=bool(
                product.get("previous_price_validated", False)
            ),
            duplicate=bool(product.get("duplicate", False)),
            future_signals=product.get("future_signals") or {},
        )


@dataclass(frozen=True, slots=True)
class ScoreResult:
    total: float
    classification: str
    components: Mapping[str, float]
    policy_version: int
    confidence: float
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class OfferIdentityResult:
    signature: str
    normalized_title: str
    canonical_link: str
    link_signature: str
    promotion_signature: str
    similarity_signature: str
    product_code: str = ""
    tokens: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PriceObservation:
    identity: str
    price: float
    observed_at: datetime
    source: str = ""
    store: str = ""
    title: str = ""
    currency: str = "BRL"
    original_url: str = ""
    image_url: str = ""
    availability: str = ""


@dataclass(frozen=True, slots=True)
class OfferHistoryResult:
    identity: str
    minimum: float
    maximum: float
    average: float
    median: float
    sample_count: int
    reliable: bool
    is_historical_low: bool
    is_near_historical_low: bool
    variation_from_previous_percent: Optional[float]
    percentile: Optional[float]
    observations: tuple[PriceObservation, ...] = ()
    standard_deviation: float = 0.0
    observed_days: int = 0
    first_price: float = 0.0
    last_price: float = 0.0
    daily_variation_percent: Optional[float] = None
    weekly_variation_percent: Optional[float] = None
    monthly_variation_percent: Optional[float] = None
    trend: str = "estavel"
    is_new_record: bool = False
    drop_percent: float = 0.0
    events: tuple[str, ...] = ()
    temporal_confidence: str = "baixa"
    history_span_days: int = 0


@dataclass(frozen=True, slots=True)
class DuplicateCheckResult:
    is_duplicate: bool
    duplicate_type: str
    previous_match: Optional[Any]
    blocked_until: Optional[datetime]
    reasons: tuple[str, ...] = ()
    shadow_mode: bool = True
    blocks_current_flow: bool = False


@dataclass(frozen=True, slots=True)
class RankedOffer:
    candidate: OfferCandidate
    score: ScoreResult
    identity: OfferIdentityResult
    duplicate: Optional[DuplicateCheckResult] = None
    history: Optional[OfferHistoryResult] = None
    rank: int = 0


@dataclass(frozen=True, slots=True)
class QueueOffer:
    id: Optional[int]
    evaluation_id: str
    product_id: str
    canonical_identity: str
    promotion_signature: str
    title: str
    store: str
    category: str
    current_price: float
    previous_price: float
    discount_percent: float
    saving_amount: float
    score: float
    classification: str
    confidence: float
    score_components: Mapping[str, float]
    status: str = "queued"
    priority: float = 0.0
    available_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    reserved_at: Optional[datetime] = None
    reserved_by: str = ""
    reservation_expires_at: Optional[datetime] = None
    attempts: int = 0
    last_error: str = ""
    blocked_reason: str = ""
    blocked_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None


@dataclass(frozen=True, slots=True)
class SkippedOffer:
    queue_item_id: int
    reason: str
    status: str


@dataclass(frozen=True, slots=True)
class SchedulerDecision:
    run_id: str
    selected_offers: tuple[QueueOffer, ...]
    skipped_offers: tuple[SkippedOffer, ...]
    selected_count: int
    hourly_remaining: int
    daily_remaining: int
    next_allowed_at: Optional[datetime]
    shadow_mode: bool = True
    affects_current_flow: bool = False
    reasons: tuple[str, ...] = ()
