from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.promotion_hunter.adapters.shopee import (
    ShopeeCollectionAdapter,
    ShopeeCollectionError,
)


class FakeShopeeScraper:
    def __init__(self, products=None):
        self.products = products or []
        self.closed = False

    def search(self, term):
        return self.products

    def close(self, page=None):
        self.closed = True


def test_adapter_requires_non_empty_keyword():
    adapter = ShopeeCollectionAdapter(scraper=FakeShopeeScraper())
    with pytest.raises(ValueError, match="não pode ser vazia"):
        adapter.collect("")
    with pytest.raises(ValueError, match="não pode ser vazia"):
        adapter.collect("   ")


def test_adapter_rejects_invalid_limit():
    adapter = ShopeeCollectionAdapter(scraper=FakeShopeeScraper())
    with pytest.raises(ValueError, match="limite"):
        adapter.collect("ssd", limit=0)
    with pytest.raises(ValueError, match="limite"):
        adapter.collect("ssd", limit=11)


def test_adapter_default_limit_is_5():
    assert ShopeeCollectionAdapter.DEFAULT_LIMIT == 5


def test_adapter_returns_empty_tuple_when_no_products():
    adapter = ShopeeCollectionAdapter(scraper=FakeShopeeScraper([]))
    result = adapter.collect("ssd")
    assert result == ()


def test_adapter_returns_products_from_search():
    products = [
        {"loja": "Shopee", "titulo": "SSD 1TB", "preco": "299,99",
         "link": "https://shopee.com.br/produto-i.123456.789"},
    ]
    adapter = ShopeeCollectionAdapter(scraper=FakeShopeeScraper(products))
    result = adapter.collect("ssd", limit=5)
    assert len(result) == 1
    assert result[0]["titulo"] == "SSD 1TB"


def test_adapter_respects_limit():
    products = [
        {"loja": "Shopee", "titulo": f"Produto {i}", "preco": "100,00",
         "link": f"https://shopee.com.br/produto-i.{i}.{i+100}"}
        for i in range(10)
    ]
    adapter = ShopeeCollectionAdapter(scraper=FakeShopeeScraper(products))
    result = adapter.collect("ssd", limit=3)
    assert len(result) == 3


def test_extract_product_id_from_i_url():
    url = "https://shopee.com.br/produto-i.123456.789"
    result = ShopeeCollectionAdapter.extract_product_id(url)
    assert result == "123456.789"


def test_extract_product_id_from_product_url():
    url = "https://shopee.com.br/product/123456/789"
    result = ShopeeCollectionAdapter.extract_product_id(url)
    assert result == "123456.789"


def test_extract_product_id_from_url_with_tracking():
    url = "https://shopee.com.br/produto-i.123456.789?tracking=abc"
    result = ShopeeCollectionAdapter.extract_product_id(url)
    assert result == "123456.789"


def test_extract_product_id_empty():
    assert ShopeeCollectionAdapter.extract_product_id("") == ""
    assert ShopeeCollectionAdapter.extract_product_id("https://br.shp.ee/abc") == ""


def test_technical_product_preserves_id():
    product = {"loja": "Shopee", "id": "123456.789", "titulo": "Teste"}
    result = ShopeeCollectionAdapter._technical_product(product)
    assert result["id"] == "123456.789"


def test_technical_product_fills_id_from_url():
    product = {"loja": "Shopee", "titulo": "Teste", "link": "https://shopee.com.br/produto-i.123456.789"}
    result = ShopeeCollectionAdapter._technical_product(product)
    assert result["id"] == "123456.789"


def test_adapter_raises_collection_error_on_exception():
    class BrokenScraper:
        def search(self, term):
            raise RuntimeError("Falha na busca")

        def close(self, page=None):
            pass

    adapter = ShopeeCollectionAdapter(scraper=BrokenScraper())
    with pytest.raises(ShopeeCollectionError):
        adapter.collect("ssd")


def test_adapter_closes_owned_scraper():
    scraper = FakeShopeeScraper()
    adapter = ShopeeCollectionAdapter(scraper=scraper)
    assert adapter._owns_scraper is False
    adapter.collect("ssd")
    assert scraper.closed is False


def test_adapter_closes_self_created_scraper():
    factory = MagicMock(return_value=FakeShopeeScraper())
    adapter = ShopeeCollectionAdapter(scraper_factory=factory)
    assert adapter._owns_scraper is True
    adapter.collect("ssd")
    factory.assert_called_once()


def test_sanitize_error_removes_credentials():
    error = RuntimeError("cookie=sensitive123")
    result = ShopeeCollectionAdapter.sanitize_error(error)
    assert "sensitive123" not in result


def test_adapter_rejects_scraper_and_factory():
    with pytest.raises(ValueError, match="não ambos"):
        ShopeeCollectionAdapter(scraper=FakeShopeeScraper(), scraper_factory=lambda: FakeShopeeScraper())