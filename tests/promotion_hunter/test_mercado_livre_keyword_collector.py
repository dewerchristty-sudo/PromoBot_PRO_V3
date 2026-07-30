import pytest

from src.promotion_hunter.adapters import MercadoLivreCollectionError
from src.promotion_hunter.collectors import MercadoLivreKeywordCollector
from src.promotion_hunter.contracts import PromotionSource


class FakeAdapter:
    def __init__(self, products=(), error=None):
        self.products = tuple(products)
        self.error = error
        self.calls = []

    def collect(self, term, limit=None):
        self.calls.append((term, limit))
        if self.error:
            raise self.error
        return self.products


def source(configuration=None, limit=5, store="Mercado Livre"):
    return PromotionSource(
        "kw", "keyword", store, "Keyword",
        (
            {"keyword": "air fryer"}
            if configuration is None else configuration
        ),
        limit=limit,
    )


def test_collector_forwards_keyword_and_limit():
    adapter = FakeAdapter([{"titulo": "Produto"}])
    result = MercadoLivreKeywordCollector(adapter).collect(source())
    assert adapter.calls == [("air fryer", 5)]
    assert result.status == "success"
    assert result.returned_count == 1


def test_collector_reports_zero_results():
    result = MercadoLivreKeywordCollector(FakeAdapter()).collect(source())
    assert result.status == "zero_results"
    assert result.products == ()


def test_collector_returns_sanitized_technical_error():
    error = MercadoLivreCollectionError("falha técnica sanitizada")
    result = MercadoLivreKeywordCollector(
        FakeAdapter(error=error)
    ).collect(source())
    assert result.status == "error"
    assert result.error_type == "MercadoLivreCollectionError"
    assert result.error_message == "falha técnica sanitizada"


@pytest.mark.parametrize("configuration", [{}, {"keyword": "   "}, {"terms": []}])
def test_collector_requires_non_empty_keyword(configuration):
    with pytest.raises(ValueError, match="palavra-chave"):
        MercadoLivreKeywordCollector(FakeAdapter()).collect(
            source(configuration=configuration)
        )


def test_collector_accepts_single_legacy_term_without_reading_it_in_service():
    adapter = FakeAdapter()
    MercadoLivreKeywordCollector(adapter).collect(
        source(configuration={"terms": ["aspirador"]})
    )
    assert adapter.calls == [("aspirador", 5)]


def test_collector_rejects_other_store_without_fallback():
    with pytest.raises(ValueError, match="somente Mercado Livre"):
        MercadoLivreKeywordCollector(FakeAdapter()).collect(
            source(store="Amazon")
        )
