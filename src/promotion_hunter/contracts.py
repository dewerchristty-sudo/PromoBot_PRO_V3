from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol, runtime_checkable


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class PromotionSource:
    source_id: str
    source_type: str
    store: str
    display_name: str
    configuration: Mapping[str, Any] = field(default_factory=dict)
    enabled: bool = True
    limit: int | None = None

    def __post_init__(self) -> None:
        for field_name in ("source_id", "source_type", "store", "display_name"):
            if not str(getattr(self, field_name) or "").strip():
                raise ValueError(f"{field_name} não pode ser vazio")
        if self.limit is not None and self.limit <= 0:
            raise ValueError("limit deve ser maior que zero")


@dataclass(frozen=True, slots=True)
class CollectionResult:
    source: PromotionSource
    products: tuple[Mapping[str, Any], ...] = ()
    status: str = "success"
    started_at: datetime = field(default_factory=utc_now)
    finished_at: datetime = field(default_factory=utc_now)
    error_type: str | None = None
    error_message: str | None = None

    @property
    def returned_count(self) -> int:
        return len(self.products)


@runtime_checkable
class PromotionCollector(Protocol):
    def collect(self, source: PromotionSource) -> CollectionResult:
        """Coleta produtos sem analisá-los ou enviá-los."""
