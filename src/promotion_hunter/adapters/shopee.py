from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any, Protocol, runtime_checkable
from urllib.parse import urlparse


@runtime_checkable
class ShopeeSearchClient(Protocol):
    def search(self, term: str) -> list[dict[str, Any]]:
        ...

    def close(self, page: Any = None) -> None:
        ...


class ShopeeCollectionError(RuntimeError):
    pass


class ShopeeCollectionAdapter:
    MIN_LIMIT = 1
    MAX_LIMIT = 10
    DEFAULT_LIMIT = 5

    def __init__(
        self,
        scraper: ShopeeSearchClient | None = None,
        scraper_factory: Callable[[], ShopeeSearchClient] | None = None,
    ) -> None:
        if scraper is not None and scraper_factory is not None:
            raise ValueError("Informe scraper ou scraper_factory, não ambos")
        self.scraper = scraper
        self.scraper_factory = scraper_factory or self._default_scraper_factory
        self._owns_scraper = scraper is None

    @staticmethod
    def _default_scraper_factory() -> ShopeeSearchClient:
        from src.stores.shopee import Shopee

        return Shopee()

    @classmethod
    def validate_limit(cls, limit: int | None) -> int:
        if limit is None:
            return cls.DEFAULT_LIMIT
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ValueError("O limite deve ser um número inteiro entre 1 e 10")
        if not cls.MIN_LIMIT <= limit <= cls.MAX_LIMIT:
            raise ValueError("O limite deve ficar entre 1 e 10 produtos")
        return limit

    @staticmethod
    def sanitize_error(error: Exception) -> str:
        message = " ".join(str(error).split())
        message = re.sub(
            r"(?i)\b(authorization|cookie|token|api[-_ ]?key)\s*[:=]\s*\S+",
            r"\1=<removido>",
            message,
        )
        message = re.sub(
            r"(?i)(https?://)([^/@\s:]+):([^/@\s]+)@",
            r"\1<credenciais-removidas>@",
            message,
        )
        message = re.sub(
            r"(?i)\b[A-Z]:\\(?:[^\\\s]+\\)+[^\\\s]*",
            "<caminho-removido>",
            message,
        )
        return message[:300] or "Falha técnica sem detalhes disponíveis"

    @staticmethod
    def extract_product_id(url: str) -> str:
        if not url:
            return ""
        from src.affiliates.validation import product_identity

        return product_identity("Shopee", url)

    @classmethod
    def _technical_product(cls, product: Mapping[str, Any]) -> dict[str, Any]:
        result = dict(product)
        if not any(result.get(name) for name in (
            "id", "product_id", "item_id", "external_id"
        )):
            url = result.get("url") or result.get("link") or ""
            product_id = cls.extract_product_id(str(url))
            if product_id:
                result["id"] = product_id
        return result

    def collect(self, term: str, limit: int | None = None) -> tuple[dict[str, Any], ...]:
        text = str(term or "").strip()
        if not text:
            raise ValueError("A palavra-chave não pode ser vazia")
        safe_limit = self.validate_limit(limit)
        scraper = self.scraper or self.scraper_factory()
        try:
            products = scraper.search(text)
            if products is None:
                products = []
            if not isinstance(products, (list, tuple)):
                raise TypeError("Shopee retornou coleção inválida")
            return tuple(
                self._technical_product(product)
                for product in products[:safe_limit]
                if isinstance(product, Mapping)
            )
        except Exception as error:
            if isinstance(error, ShopeeCollectionError):
                raise
            raise ShopeeCollectionError(
                self.sanitize_error(error)
            ) from error
        finally:
            if self._owns_scraper:
                closer = getattr(scraper, "close", None)
                if callable(closer):
                    try:
                        closer()
                    except Exception:
                        pass