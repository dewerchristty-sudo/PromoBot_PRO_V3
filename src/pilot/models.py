from dataclasses import dataclass, field
from datetime import datetime


PILOT_STATES = {
    "DISABLED", "CONFIGURATION_REQUIRED", "READY", "DRY_RUN",
    "AWAITING_CONFIRMATION", "AUTHORIZED", "SENT", "FAILED",
    "AUTO_STOPPED",
}


@dataclass(frozen=True, slots=True)
class PilotProduct:
    title: str
    store: str
    current_price: float
    previous_price: float
    discount_percent: float
    affiliate_url: str
    affiliate_valid: bool
    image_available: bool
    score: float
    threshold: float
    operationally_ready: bool
    selected: bool
    approved: bool = False
    identity: str = ""


@dataclass(frozen=True, slots=True)
class PilotDecision:
    state: str
    operationally_ready: bool
    approved: bool
    selected: bool
    authorized: bool
    sent: bool
    reason: str
    transport_called: bool = False
    auto_stopped: bool = False
    audit: tuple[str, ...] = ()


@dataclass(slots=True)
class PilotAuthorization:
    authorization_id: str
    product_identity: str
    created_at: datetime
    expires_at: datetime
    consumed: bool = False
    state: str = "AUTHORIZED"


@dataclass(frozen=True, slots=True)
class PilotConfigurationStatus:
    state: str
    valid: bool
    reasons: tuple[str, ...] = ()
    masked_group: str = "(ausente)"
    details: dict = field(default_factory=dict)
