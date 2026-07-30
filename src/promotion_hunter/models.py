from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DecisionStatus(str, Enum):
    APPROVED = "aprovado"
    DISCARDED = "descartado"
    PENDING = "pendente"


@dataclass(frozen=True, slots=True)
class NormalizedProduct:
    deduplication_key: str
    store: str
    title: str
    external_id: str = ""
    url: str = ""
    image_url: str = ""
    category: str = ""
    current_price: float | None = None
    previous_price: float | None = None
    discount_percent: float | None = None
    saving_amount: float | None = None
    source_ids: tuple[str, ...] = ()
    source_types: tuple[str, ...] = ()
    collected_at: datetime = field(default_factory=utc_now)
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False, repr=False)

    def merge_provenance(self, other: "NormalizedProduct") -> "NormalizedProduct":
        return replace(
            self,
            source_ids=tuple(dict.fromkeys(self.source_ids + other.source_ids)),
            source_types=tuple(
                dict.fromkeys(self.source_types + other.source_types)
            ),
        )

    def pipeline_payload(self) -> dict[str, Any]:
        payload = dict(self.raw)
        payload.update({
            "id": self.external_id,
            "loja": self.store,
            "titulo": self.title,
            "url": self.url,
            "imagem": self.image_url,
            "categoria_manual": self.category,
            "preco_atual": self.current_price,
            "preco_anterior": self.previous_price,
            "desconto_percentual": self.discount_percent,
            "economia": self.saving_amount,
        })
        return payload

    def commercial_snapshot(self) -> tuple[Any, ...]:
        return (
            self.deduplication_key,
            self.store,
            self.title,
            self.external_id,
            self.url,
            self.image_url,
            self.category,
            self.current_price,
            self.previous_price,
            self.discount_percent,
            self.saving_amount,
        )


@dataclass(frozen=True, slots=True)
class HunterDecision:
    product_key: str
    status: DecisionStatus
    reason: str
    score: float | None
    classification: str | None
    pipeline_run_id: str | None
    source_ids: tuple[str, ...]
    created_at: datetime = field(default_factory=utc_now)
    delivery_payload: Mapping[str, Any] = field(
        default_factory=dict,
        compare=False,
        repr=False,
    )


@dataclass(frozen=True, slots=True)
class SourceRunResult:
    source_id: str
    status: str
    returned_count: int
    normalized_count: int
    added_count: int
    error_type: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class HunterRunResult:
    run_id: str
    status: str
    source_runs: tuple[SourceRunResult, ...]
    collected_count: int
    unique_count: int
    decisions: tuple[HunterDecision, ...]
    normalized_products: tuple[NormalizedProduct, ...]
    started_at: datetime
    finished_at: datetime
