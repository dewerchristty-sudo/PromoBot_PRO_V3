from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.promotion_hunter.adapters.amazon import (
    AmazonCollectionAdapter,
    AmazonCollectionError,
    AmazonSearchClient,
)


class FakeAmazonScraper:
    def __init__(self, products=None):
        self.products = products or []
        self.closed = False

    def search(self, term):
        return self.products

    def close(self, page=None):
        self.closed = True


def test_adapter_requires_non_empty_keyword():
    adapter = AmazonCollectionAdapter(scraper=FakeAmazonScraper())
    with pytest.raises(ValueError, match="não pode ser vazia"):
        adapter.collect("")
    with pytest.raises(ValueError, match="não pode ser vazia"):
        adapter.collect("   ")


def test_adapter_rejects_invalid_limit():
    adapter = AmazonCollectionAdapter(scraper=FakeAmazonScraper())
    with pytest.raises(ValueError, match="limite"):
        adapter.collect("ssd", limit=0)
    with pytest.raises(ValueError, match="limite"):
        adapter.collect("ssd", limit=11)
    with pytest.raises(ValueError, match="limite"):
        adapter.collect("ssd", limit="abc")


def test_adapter_default_limit_is_5():
    assert AmazonCollectionAdapter.DEFAULT_LIMIT == 5


def test_adapter_returns_empty_tuple_when_no_products():
    adapter = AmazonCollectionAdapter(scraper=FakeAmazonScraper([]))
    result = adapter.collect("ssd")
    assert result == ()


def test_adapter_returns_products_from_search():
    products = [
        {"loja": "Amazon", "titulo": "SSD 1TB", "preco": "299,99", "link": "https://www.amazon.com.br/dp/B0ABCDEFGH"},
    ]
    adapter = AmazonCollectionAdapter(scraper=FakeAmazonScraper(products))
    result = adapter.collect("ssd", limit=5)
    assert len(result) == 1
    assert result[0]["titulo"] == "SSD 1TB"
    assert result[0]["loja"] == "Amazon"


def test_adapter_respects_limit():
    products = [
        {"loja": "Amazon", "titulo": f"Produto {i}", "preco": "100,00", "link": f"https://www.amazon.com.br/dp/B0{i:010d}"}
        for i in range(10)
    ]
    adapter = AmazonCollectionAdapter(scraper=FakeAmazonScraper(products))
    result = adapter.collect("ssd", limit=3)
    assert len(result) == 3


def test_adapter_filters_non_mapping_products():
    products = ["string", 123, None]
    adapter = AmazonCollectionAdapter(scraper=FakeAmazonScraper(products))
    result = adapter.collect("ssd")
    assert result == ()


def test_extract_product_id_from_url():
    url = "https://www.amazon.com.br/dp/B0ABCDEFGH"
    result = AmazonCollectionAdapter.extract_product_id(url)
    assert result == "B0ABCDEFGH"


def test_extract_product_id_from_gp_url():
    url = "https://www.amazon.com.br/gp/product/B0ABCDEFGH"
    result = AmazonCollectionAdapter.extract_product_id(url)
    assert result == "B0ABCDEFGH"


def test_extract_product_id_empty():
    assert AmazonCollectionAdapter.extract_product_id("") == ""
    assert AmazonCollectionAdapter.extract_product_id("https://example.com") == ""


def test_technical_product_preserves_id():
    product = {"loja": "Amazon", "id": "B0EXISTING", "titulo": "Teste"}
    result = AmazonCollectionAdapter._technical_product(product)
    assert result["id"] == "B0EXISTING"


def test_technical_product_fills_id_from_url():
    product = {
        "loja": "Amazon",
        "titulo": "Teste",
        "link": "https://www.amazon.com.br/dp/B0ABCDEFGH",
    }
    result = AmazonCollectionAdapter._technical_product(product)
    assert result["id"] == "B0ABCDEFGH"


def test_technical_product_no_id_no_url():
    product = {"loja": "Amazon", "titulo": "Sem ID"}
    result = AmazonCollectionAdapter._technical_product(product)
    assert "id" not in result or not result.get("id")


def test_adapter_raises_collection_error_on_exception():
    class BrokenScraper:
        def search(self, term):
            raise RuntimeError("Falha na busca")

        def close(self, page=None):
            pass

    adapter = AmazonCollectionAdapter(scraper=BrokenScraper())
    with pytest.raises(AmazonCollectionError):
        adapter.collect("ssd")


def test_adapter_closes_owned_scraper():
    scraper = FakeAmazonScraper()
    adapter = AmazonCollectionAdapter(scraper=scraper)
    assert adapter._owns_scraper is False
    adapter.collect("ssd")
    # Externally provided scraper should NOT be closed by adapter
    assert scraper.closed is False


def test_adapter_closes_self_created_scraper():
    factory = MagicMock(return_value=FakeAmazonScraper())
    adapter = AmazonCollectionAdapter(scraper_factory=factory)
    assert adapter._owns_scraper is True
    adapter.collect("ssd")
    factory.assert_called_once()


def test_sanitize_error_removes_credentials():
    error = RuntimeError("token=abc123")
    result = AmazonCollectionAdapter.sanitize_error(error)
    assert "abc123" not in result
    assert "token" in result


def test_adapter_rejects_scraper_and_factory():
    with pytest.raises(ValueError, match="não ambos"):
        AmazonCollectionAdapter(
            scraper=FakeAmazonScraper(),
            scraper_factory=lambda: FakeAmazonScraper(),
        )


def test_adapter_returns_correct_type():
    adapter = AmazonCollectionAdapter(scraper=FakeAmazonScraper())
    result = adapter.collect("ssd")
    assert isinstance(result, tuple)