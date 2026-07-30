from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from ..adapters import ShopeeCollectionError
from ..contracts import CollectionResult, PromotionSource


class KeywordCollectionAdapter(Protocol):
    def collect(self, term: str, limit: int | None = None) -> tuple[dict, ...]:
        ...


class ShopeeKeywordCollector:
    SOURCE_TYPE = "keyword"
    STORE = "shopee"

    def __init__(self, adapter: KeywordCollectionAdapter) -> None:
        self.adapter = adapter

    @staticmethod
    def _keyword(source: PromotionSource) -> str:
        keyword = source.configuration.get("keyword")
        if keyword is None:
            terms = source.configuration.get("terms")
            if isinstance(terms, (list, tuple)) and len(terms) == 1:
                keyword = terms[0]
        text = str(keyword or "").strip()
        if not text:
            raise ValueError("Fonte keyword exige uma palavra-chave não vazia")
        return text

    def collect(self, source: PromotionSource) -> CollectionResult:
        if source.source_type.strip().casefold() != self.SOURCE_TYPE:
            raise ValueError("O coletor aceita somente fontes do tipo keyword")
        if source.store.strip().casefold() != self.STORE:
            raise ValueError("O coletor aceita somente Shopee")

        started_at = datetime.now(timezone.utc)
        keyword = self._keyword(source)
        try:
            products = self.adapter.collect(keyword, source.limit)
        except ShopeeCollectionError as error:
            return CollectionResult(
                source=source,
                status="error",
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
                error_type=type(error).__name__,
                error_message=str(error),
            )
        return CollectionResult(
            source=source,
            products=tuple(products),
            status="success" if products else "zero_results",
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        )