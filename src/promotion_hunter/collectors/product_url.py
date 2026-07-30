from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping, Any

from ..adapters.product_url import ProductUrlCollectionError
from ..contracts import CollectionResult, PromotionSource


class ProductUrlCollector:
    SOURCE_TYPE = "product_url"

    def __init__(self, adapter) -> None:
        self.adapter = adapter

    @staticmethod
    def _url(source: PromotionSource) -> str:
        url = source.configuration.get("product_url")
        if not url:
            raise ValueError("Fonte product_url exige uma URL não vazia")
        return str(url).strip()

    def collect(self, source: PromotionSource) -> CollectionResult:
        if source.source_type.strip().casefold() != self.SOURCE_TYPE:
            raise ValueError("O coletor aceita somente fontes do tipo product_url")

        started_at = datetime.now(timezone.utc)
        url = self._url(source)
        try:
            product = self.adapter.collect(url)
        except ProductUrlCollectionError as error:
            return CollectionResult(
                source=source,
                status="error",
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
                error_type=type(error).__name__,
                error_message=str(error),
            )

        # Garantir que o produto tenha um identificador de loja
        if isinstance(product, Mapping):
            product = dict(product)

        return CollectionResult(
            source=source,
            products=(product,),
            status="success",
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
        )