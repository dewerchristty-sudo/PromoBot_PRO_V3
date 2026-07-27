from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Mapping, Optional, Tuple


class ApprovalDecision(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class PriceMovement(str, Enum):
    UNKNOWN = "unknown"
    UNCHANGED = "unchanged"
    DECREASED = "decreased"
    INCREASED = "increased"


@dataclass(frozen=True)
class OfferSnapshot:
    product_key: str
    store: str
    title: str
    current_price: float
    url: str
    category: str = ""
    group: str = ""
    previous_price: Optional[float] = None
    captured_at: datetime = field(default_factory=datetime.now)
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PublicationPlan:
    plan_id: str
    offer: OfferSnapshot
    scheduled_for: datetime
    destination_key: str
    paused: bool = False
    created_at: datetime = field(default_factory=datetime.now)


@dataclass(frozen=True)
class PriceObservation:
    product_key: str
    store: str
    price: float
    observed_at: datetime = field(default_factory=datetime.now)


@dataclass(frozen=True)
class PriceAnalysis:
    product_key: str
    movement: PriceMovement
    current_price: float
    prior_price: Optional[float]
    absolute_change: float = 0.0
    percentage_change: float = 0.0


@dataclass(frozen=True)
class ApprovalBatch:
    batch_id: str
    product_keys: Tuple[str, ...]
    decisions: Mapping[str, ApprovalDecision]
