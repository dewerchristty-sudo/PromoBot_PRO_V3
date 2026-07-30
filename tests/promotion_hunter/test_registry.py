import pytest

from src.promotion_hunter.contracts import PromotionSource
from src.promotion_hunter.registry import (
    CollectorRegistry,
    UnsupportedPromotionSource,
)
from tests.promotion_hunter.fakes import FakeCollector


def source(store="Mercado Livre", source_type="keyword"):
    return PromotionSource("source", source_type, store, "Fonte")


def test_registry_resolves_registered_collector_without_service_changes():
    registry = CollectorRegistry()
    collector = FakeCollector()
    registry.register("Mercado Livre", "custom_fake", collector)
    assert registry.resolve(source(source_type="custom_fake")) is collector


def test_unregistered_collector_has_clear_error():
    with pytest.raises(UnsupportedPromotionSource, match="Fonte não suportada"):
        CollectorRegistry().resolve(source())


def test_shopee_is_now_supported_by_registry():
    registry = CollectorRegistry()
    collector = FakeCollector()
    registry.register("Shopee", "keyword", collector)
    result = registry.resolve(source(store="Shopee"))
    assert result is collector


def test_amazon_is_now_supported_by_registry():
    registry = CollectorRegistry()
    collector = FakeCollector()
    registry.register("Amazon", "keyword", collector)
    result = registry.resolve(source(store="Amazon"))
    assert result is collector
