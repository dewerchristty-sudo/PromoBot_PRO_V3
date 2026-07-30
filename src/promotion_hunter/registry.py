from __future__ import annotations

from typing import Final

from .contracts import PromotionCollector, PromotionSource


class UnsupportedPromotionSource(LookupError):
    pass


class CollectorRegistry:
    SUPPORTED_STORES: Final[frozenset[str]] = frozenset({"mercado livre", "amazon", "shopee"})

    def __init__(self) -> None:
        self._collectors: dict[tuple[str, str], PromotionCollector] = {}

    @staticmethod
    def _key(store: str, source_type: str) -> tuple[str, str]:
        return store.strip().casefold(), source_type.strip().casefold()

    def register(
        self,
        store: str,
        source_type: str,
        collector: PromotionCollector,
    ) -> None:
        key = self._key(store, source_type)
        if key[0] not in self.SUPPORTED_STORES:
            raise UnsupportedPromotionSource(
                f"Loja não suportada nesta versão: {store}"
            )
        if not isinstance(collector, PromotionCollector):
            raise TypeError("collector deve implementar PromotionCollector")
        self._collectors[key] = collector

    def resolve(self, source: PromotionSource) -> PromotionCollector:
        key = self._key(source.store, source.source_type)
        if key[0] not in self.SUPPORTED_STORES:
            raise UnsupportedPromotionSource(
                f"Loja não suportada nesta versão: {source.store}"
            )
        try:
            return self._collectors[key]
        except KeyError as exc:
            raise UnsupportedPromotionSource(
                "Fonte não suportada: "
                f"loja={source.store}, tipo={source.source_type}"
            ) from exc
