from __future__ import annotations

import pytest

from src.promotion_hunter.collectors.amazon_keyword import AmazonKeywordCollector
from src.promotion_hunter.contracts import PromotionSource
from src.promotion_hunter.adapters.amazon import AmazonCollectionError


class FakeAdapter:
    def __init__(self, products=None, error=None):
        self.products = products or []
        self.error = error
        self.last_term = None
        self.last_limit = None

    def collect(self, term, limit=None):
        self.last_term = term
        self.last_limit = limit
        if self.error:
            raise self.error
        return tuple(self.products)


def source(store="Amazon", keyword="ssd"):
    return PromotionSource(
        "test-source", "keyword", store, "Teste",
        {"keyword": keyword}, limit=5,
    )


def test_collector_rejects_non_keyword_type():
    collector = AmazonKeywordCollector(FakeAdapter())
    src = PromotionSource("s", "url", "Amazon", "Teste")
    with pytest.raises(ValueError, match="somente fontes do tipo keyword"):
        collector.collect(src)


def test_collector_rejects_non_amazon_store():
    collector = AmazonKeywordCollector(FakeAdapter())
    src = PromotionSource("s", "keyword", "Mercado Livre", "Teste", {"keyword": "x"})
    with pytest.raises(ValueError, match="somente Amazon"):
        collector.collect(src)


def test_collector_rejects_empty_keyword():
    collector = AmazonKeywordCollector(FakeAdapter())
    src = source(keyword="")
    with pytest.raises(ValueError, match="palavra-chave não vazia"):
        collector.collect(src)


def test_collector_returns_success_with_products():
    adapter = FakeAdapter(products=[{"loja": "Amazon", "titulo": "SSD", "id": "B0TEST"}])
    collector = AmazonKeywordCollector(adapter)
    result = collector.collect(source())
    assert result.status == "success"
    assert len(result.products) == 1
    assert result.products[0]["id"] == "B0TEST"


def test_collector_returns_zero_results_when_empty():
    adapter = FakeAdapter(products=[])
    collector = AmazonKeywordCollector(adapter)
    result = collector.collect(source())
    assert result.status == "zero_results"
    assert result.returned_count == 0


def test_collector_returns_error_on_collection_error():
    adapter = FakeAdapter(error=AmazonCollectionError("Falha técnica"))
    collector = AmazonKeywordCollector(adapter)
    result = collector.collect(source())
    assert result.status == "error"
    assert result.error_type == "AmazonCollectionError"


def test_collector_passes_limit_to_adapter():
    adapter = FakeAdapter()
    collector = AmazonKeywordCollector(adapter)
    src = source(keyword="ssd")
    collector.collect(src)
    assert adapter.last_term == "ssd"
    assert adapter.last_limit == 5


def test_collector_uses_terms_as_keyword():
    adapter = FakeAdapter()
    collector = AmazonKeywordCollector(adapter)
    src = PromotionSource(
        "s", "keyword", "Amazon", "SSD",
        {"terms": ["ssd 1tb"]}, limit=3,
    )
    collector.collect(src)
    assert adapter.last_term == "ssd 1tb"
    assert adapter.last_limit == 3


def test_collector_requires_keyword_for_multiple_terms():
    adapter = FakeAdapter()
    collector = AmazonKeywordCollector(adapter)
    src = PromotionSource(
        "s", "keyword", "Amazon", "Multi",
        {"terms": ["term1", "term2"]}, limit=5,
    )
    with pytest.raises(ValueError, match="palavra-chave não vazia"):
        collector.collect(src)
