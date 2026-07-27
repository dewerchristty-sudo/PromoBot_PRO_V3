from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True, slots=True)
class AffiliateResult:
    store: str
    original_url: str
    affiliate_url: str = ""
    provider: str = ""
    status: str = "NOT_CONFIGURED"
    source: str = ""
    error: str = ""
    elapsed_ms: float = 0.0
    cache_hit: bool = False

    @property
    def valid(self):
        return self.status in {"GENERATED", "CACHED", "PROVIDED"}


@dataclass(frozen=True, slots=True)
class AffiliateMetrics:
    requests: int = 0
    generated: int = 0
    cache_hits: int = 0
    provided: int = 0
    failures: int = 0
    invalid: int = 0
    average_ms: float = 0.0
    by_store: Mapping[str, Mapping[str, int]] = field(default_factory=dict)
