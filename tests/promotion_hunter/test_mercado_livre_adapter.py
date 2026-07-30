import inspect

import pytest

from src.promotion_hunter.adapters import (
    MercadoLivreCollectionAdapter,
    MercadoLivreCollectionError,
)
from src.promotion_hunter.normalization import ProductNormalizer
from src.promotion_hunter.contracts import PromotionSource


class FakeMercadoLivre:
    def __init__(self, products=(), error=None, close_error=None):
        self.products = list(products)
        self.error = error
        self.close_error = close_error
        self.terms = []
        self.close_calls = 0

    def search(self, term):
        self.terms.append(term)
        if self.error:
            raise self.error
        return self.products

    def close(self, page=None):
        self.close_calls += 1
        if self.close_error:
            raise self.close_error


def product(index, link=None):
    return {
        "loja": "Mercado Livre",
        "titulo": f"Produto {index}",
        "preco": f"R$ {index},90",
        "link": link or f"https://produto.mercadolivre.com.br/MLB-{index}",
        "imagem": f"https://http2.mlstatic.com/{index}.jpg",
    }


def test_adapter_forwards_term_limits_results_and_closes():
    scraper = FakeMercadoLivre([product(index) for index in range(1, 9)])
    result = MercadoLivreCollectionAdapter(scraper=scraper).collect("ssd 1tb")
    assert scraper.terms == ["ssd 1tb"]
    assert len(result) == 5
    assert scraper.close_calls == 1


@pytest.mark.parametrize("limit", [0, -1, 11, 50])
def test_adapter_rejects_limits_outside_safe_range(limit):
    with pytest.raises(ValueError, match="entre 1 e 10"):
        MercadoLivreCollectionAdapter(
            scraper=FakeMercadoLivre()
        ).collect("produto", limit)


def test_adapter_closes_after_error_and_sanitizes_details():
    scraper = FakeMercadoLivre(error=RuntimeError(
        r"token=segredo C:\Users\pessoa\arquivo.txt"
    ))
    with pytest.raises(MercadoLivreCollectionError) as captured:
        MercadoLivreCollectionAdapter(scraper=scraper).collect("produto")
    assert scraper.close_calls == 1
    assert "segredo" not in str(captured.value)
    assert "pessoa" not in str(captured.value)


def test_scraper_value_error_is_also_a_controlled_technical_error():
    scraper = FakeMercadoLivre(error=ValueError("resposta interna inválida"))
    with pytest.raises(MercadoLivreCollectionError, match="resposta interna"):
        MercadoLivreCollectionAdapter(scraper=scraper).collect("produto")
    assert scraper.close_calls == 1


def test_repeated_close_failure_is_non_blocking():
    scraper = FakeMercadoLivre(
        [product(1)],
        close_error=RuntimeError("já fechado"),
    )
    adapter = MercadoLivreCollectionAdapter(scraper=scraper)
    assert len(adapter.collect("produto")) == 1
    assert len(adapter.collect("produto")) == 1
    assert scraper.close_calls == 2


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://produto.mercadolivre.com.br/MLB-123456", "MLB123456"),
        ("https://www.mercadolivre.com.br/p/MLB123456", "MLB123456"),
        ("https://www.mercadolivre.com.br/up/MLBU123456", "MLBU123456"),
        ("https://www.mercadolivre.com.br/x?wid=MLB123456", "MLB123456"),
        (
            "https://www.mercadolivre.com.br/x?"
            "pdp_filters=item_id%3AMLB123456",
            "MLB123456",
        ),
        ("https://example.com/MLB-123456", ""),
        ("https://www.mercadolivre.com.br/lista/produto-123456", ""),
    ],
)
def test_extracts_only_proven_mercado_livre_identity(url, expected):
    assert MercadoLivreCollectionAdapter.extract_product_id(url) == expected


def test_realistic_product_keeps_absent_commercial_data_absent():
    source = PromotionSource(
        "kw", "keyword", "Mercado Livre", "Keyword",
        {"keyword": "ssd"}, limit=5,
    )
    raw = MercadoLivreCollectionAdapter(
        scraper=FakeMercadoLivre([product(123)])
    ).collect("ssd")[0]
    normalized = ProductNormalizer().normalize(raw, source)
    assert normalized.external_id == "MLB123"
    assert normalized.previous_price is None
    assert normalized.discount_percent is None
    assert normalized.saving_amount is None
    assert normalized.category == ""
    assert "disponibilidade" not in normalized.raw


def test_adapter_is_only_new_layer_that_imports_scraper():
    from src.promotion_hunter import service
    from src.promotion_hunter.collectors import mercado_livre_keyword

    assert "src.stores.mercado_livre" in inspect.getsource(
        MercadoLivreCollectionAdapter
    )
    assert "MercadoLivre" not in inspect.getsource(service)
    collector_source = inspect.getsource(mercado_livre_keyword)
    assert "playwright" not in collector_source.casefold()
    assert "StoreManager" not in collector_source
