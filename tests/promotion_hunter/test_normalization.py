from decimal import Decimal

import pytest

from src.promotion_hunter.contracts import PromotionSource
from src.promotion_hunter.normalization import ProductNormalizer


def test_two_source_types_generate_same_commercial_contract():
    normalizer = ProductNormalizer()
    keyword = PromotionSource("kw", "keyword", "Mercado Livre", "Keyword")
    category = PromotionSource(
        "cat", "official_category", "Mercado Livre", "Categoria"
    )
    first = normalizer.normalize({
        "id": "MLB123",
        "titulo": "Produto",
        "preco_atual": "R$ 99,90",
        "url": "https://produto.mercadolivre.com.br/MLB123?tracking=x",
    }, keyword)
    second = normalizer.normalize({
        "product_id": "MLB123",
        "title": "Produto",
        "current_price": 99.90,
        "product_url": "https://produto.mercadolivre.com.br/MLB123",
    }, category)
    assert first.commercial_snapshot() == second.commercial_snapshot()
    assert first.source_types != second.source_types


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1.040", 1040.00),
        ("1.199", 1199.00),
        ("1.125", 1125.00),
        ("1.357", 1357.00),
        ("1.040,90", 1040.90),
        ("R$ 1.040,90", 1040.90),
        ("1040,90", 1040.90),
        ("19.99", 19.99),
        ("  R$ 99,90  ", 99.90),
        ("12,50", 12.50),
        ("12.345,67", 12345.67),
        (1040, 1040.00),
        (1040.90, 1040.90),
        (Decimal("1040.90"), 1040.90),
    ],
)
def test_money_contract_preserves_brazilian_and_numeric_values(value, expected):
    assert ProductNormalizer._money_number(value) == expected


@pytest.mark.parametrize("value", ["", None, "inválido"])
def test_money_contract_returns_none_for_absent_or_invalid_value(value):
    assert ProductNormalizer._money_number(value) is None


def test_absent_previous_price_remains_absent():
    source = PromotionSource("kw", "keyword", "Mercado Livre", "Keyword")
    product = ProductNormalizer().normalize({
        "id": "MLB1", "titulo": "Produto", "preco": "1.040",
    }, source)
    assert product.current_price == 1040
    assert product.previous_price is None
    assert product.discount_percent is None


def test_mercado_livre_preco_antigo_with_g_is_normalized():
    """Mercado Livre retorna 'preco_antigo' (com G).
    O normalizador deve reconhecer esse campo como preço anterior."""
    source = PromotionSource("url", "product_url", "Mercado Livre", "URL")
    product = ProductNormalizer().normalize({
        "id": "MLBU3401120243",
        "titulo": "Armario Madesa",
        "preco": "699,99",
        "preco_antigo": "858,81",
    }, source)
    assert product.current_price == 699.99
    assert product.previous_price == 858.81
    assert product.previous_price > product.current_price


def test_preco_anterior_with_r_still_recognized():
    """preco_anterior (com R) continua funcionando como antes."""
    source = PromotionSource("kw", "keyword", "Mercado Livre", "Keyword")
    product = ProductNormalizer().normalize({
        "id": "MLB1", "titulo": "Produto", "preco": "100",
        "preco_anterior": "150",
    }, source)
    assert product.current_price == 100
    assert product.previous_price == 150


def test_previous_price_english_still_recognized():
    """previous_price (inglês) continua funcionando."""
    source = PromotionSource("kw", "keyword", "Amazon", "Keyword")
    product = ProductNormalizer().normalize({
        "id": "B123", "titulo": "Produto", "preco": "50",
        "previous_price": "80",
    }, source)
    assert product.current_price == 50
    assert product.previous_price == 80


def test_preco_anterior_overrides_preco_antigo_when_both_present():
    """Quando ambos existem, preco_anterior (R) tem precedência."""
    source = PromotionSource("url", "product_url", "Mercado Livre", "URL")
    product = ProductNormalizer().normalize({
        "id": "MLB1", "titulo": "Produto", "preco": "100",
        "preco_anterior": "200",
        "preco_antigo": "150",
    }, source)
    assert product.previous_price == 200
