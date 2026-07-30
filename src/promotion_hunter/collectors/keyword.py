from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Iterable, Mapping, Any

from ..contracts import CollectionResult, PromotionSource


class KeywordCollector:
    def __init__(
        self,
        collect_term: Callable[
            [str, PromotionSource],
            Iterable[Mapping[str, Any]],
        ],
    ) -> None:
        self.collect_term = collect_term

    def collect(self, source: PromotionSource) -> CollectionResult:
        started_at = datetime.now(timezone.utc)
        terms = source.configuration.get("terms")
        if not isinstance(terms, (list, tuple)) or not terms:
            raise ValueError("Fonte keyword exige uma lista não vazia de terms")
        products: list[Mapping[str, Any]] = []
        for term in terms:
            text = str(term).strip()
            if not text:
                continue
            products.extend(self.collect_term(text, source))
        return CollectionResult(
            source=source,
            products=tuple(products),
            status="success" if products else "zero_results",
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        )
