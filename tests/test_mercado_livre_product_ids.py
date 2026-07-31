"""Testes de suporte a Product IDs MLB e MLBU do Mercado Livre.

Cobre:
- normalize_product_id()
- identity_from_url()
- product_identity()
- MercadoLivreAffiliateProvider.generate()
- product_link() (testes unitarios de logica)
- Deduplicacao entre MLB e MLBU
"""

import pytest
from src.stores.mercado_livre import MercadoLivre
from src.affiliates.mercado_livre import MercadoLivreAffiliateProvider
from src.affiliates.validation import product_identity, preserves_product
from src.affiliates.config import StoreAffiliateConfig


# ============================================================
# normalize_product_id
# ============================================================

class TestNormalizeProductId:

    @pytest.mark.parametrize("raw,expected", [
        ("MLB5881541102", "MLB5881541102"),
        ("MLB-5881541102", "MLB5881541102"),
        ("MLBU3401120243", "MLBU3401120243"),
        ("MLBU-3401120243", "MLBU3401120243"),
        ("mlb5881541102", "MLB5881541102"),
        ("mlbu3401120243", "MLBU3401120243"),
        ("mlb-5881541102", "MLB5881541102"),
        ("mlbu-3401120243", "MLBU3401120243"),
    ])
    def test_normalize_valid_ids(self, raw, expected):
        assert MercadoLivre.normalize_product_id(raw) == expected

    @pytest.mark.parametrize("raw", [
        "",
        None,
        "   ",
        "ABC123",
        "1234567890",
        "MLBX123",
        "MLB",
        "MLBU",
    ])
    def test_normalize_invalid_ids_returns_empty(self, raw):
        assert MercadoLivre.normalize_product_id(raw) == ""

    def test_mlbu_is_not_converted_to_mlb(self):
        result = MercadoLivre.normalize_product_id("MLBU3401120243")
        assert result.startswith("MLBU")
        assert not result.startswith("MLB340")  # garantir que nao vira MLB340...

    def test_mlb_and_mlbu_are_different(self):
        mlb = MercadoLivre.normalize_product_id("MLB3401120243")
        mlbu = MercadoLivre.normalize_product_id("MLBU3401120243")
        assert mlb != mlbu
        assert mlb == "MLB3401120243"
        assert mlbu == "MLBU3401120243"


# ============================================================
# identity_from_url
# ============================================================

class TestIdentityFromUrl:

    def test_mlb_url_traditional(self):
        url = "https://produto.mercadolivre.com.br/MLB-5881541102"
        identity = MercadoLivre.identity_from_url(url)
        assert identity.id_item == "MLB5881541102"
        assert identity.tipo.value == "ITEM"

    def test_mlb_url_sem_hifen(self):
        url = "https://www.mercadolivre.com.br/MLB5881541102"
        # URL sem hifen tipicamente redireciona, mas o path e capturado
        identity = MercadoLivre.identity_from_url(url)
        assert identity.id_item == "MLB5881541102"

    def test_mlbu_up_url(self):
        url = "https://www.mercadolivre.com.br/armario-de-cozinha-compacta-137-cm-emilly-madesa-011-rc/up/MLBU3401120243"
        identity = MercadoLivre.identity_from_url(url)
        assert identity.id_catalogo == "MLBU3401120243"
        assert identity.tipo.value == "CATALOGO"

    def test_mlbu_up_url_sem_produto(self):
        url = "https://www.mercadolivre.com.br/up/MLBU3401120243"
        identity = MercadoLivre.identity_from_url(url)
        assert identity.id_catalogo == "MLBU3401120243"

    def test_mlb_catalog_url(self):
        url = "https://www.mercadolivre.com.br/p/MLB1234567890"
        identity = MercadoLivre.identity_from_url(url)
        assert identity.id_catalogo == "MLB1234567890"
        assert identity.tipo.value == "CATALOGO"

    def test_mlbu_catalog_url(self):
        url = "https://www.mercadolivre.com.br/p/MLBU1234567890"
        identity = MercadoLivre.identity_from_url(url)
        assert identity.id_catalogo == "MLBU1234567890"

    def test_mlb_with_wid_param(self):
        url = "https://www.mercadolivre.com.br/mlb-123?wid=MLB5881541102"
        identity = MercadoLivre.identity_from_url(url)
        assert identity.id_item == "MLB5881541102"

    def test_mlbu_with_wid_param(self):
        url = "https://www.mercadolivre.com.br/mlb-123?wid=MLBU3401120243"
        identity = MercadoLivre.identity_from_url(url)
        assert identity.id_item == "MLBU3401120243"

    def test_mlb_pdp_filters(self):
        url = "https://www.mercadolivre.com.br/?pdp_filters=item_id:MLB5881541102"
        identity = MercadoLivre.identity_from_url(url)
        assert identity.id_item == "MLB5881541102"

    def test_mlbu_pdp_filters(self):
        url = "https://www.mercadolivre.com.br/?pdp_filters=item_id:MLBU3401120243"
        identity = MercadoLivre.identity_from_url(url)
        assert identity.id_item == "MLBU3401120243"


# ============================================================
# product_identity (validation.py)
# ============================================================

class TestProductIdentity:

    @pytest.mark.parametrize("url,expected", [
        ("MLB5881541102", "MLB5881541102"),
        ("MLB-5881541102", "MLB5881541102"),
        ("MLBU3401120243", "MLBU3401120243"),
        ("MLBU-3401120243", "MLBU3401120243"),
        ("https://produto.mercadolivre.com.br/MLB-5881541102", "MLB5881541102"),
        ("https://www.mercadolivre.com.br/armario-de-cozinha/up/MLBU3401120243", "MLBU3401120243"),
    ])
    def test_product_identity_mlb_mlbu(self, url, expected):
        assert product_identity("Mercado Livre", url) == expected

    def test_product_identity_differentiates_mlb_from_mlbu(self):
        mlb = product_identity("Mercado Livre", "MLB5881541102")
        mlbu = product_identity("Mercado Livre", "MLBU5881541102")
        assert mlb != mlbu
        assert mlb == "MLB5881541102"
        assert mlbu == "MLBU5881541102"

    def test_product_identity_empty_for_amazon(self):
        # Garantir que nao ha efeito colateral: Amazon permanece inalterado
        result = product_identity("Amazon", "https://www.amazon.com.br/dp/B0ABCDEFGH")
        assert result == "B0ABCDEFGH"

    def test_product_identity_empty_for_unknown(self):
        assert product_identity("Mercado Livre", "texto qualquer sem id") == ""


# ============================================================
# preserves_product
# ============================================================

class TestPreservesProduct:

    def test_preserves_mlb(self):
        original = "https://produto.mercadolivre.com.br/MLB-5881541102"
        affiliate = "https://meli.la/abc123"
        assert preserves_product("Mercado Livre", original, affiliate)

    def test_preserves_mlbu(self):
        original = "https://www.mercadolivre.com.br/up/MLBU3401120243"
        affiliate = "https://meli.la/abc456"
        assert preserves_product("Mercado Livre", original, affiliate)

    def test_does_not_preserve_different_products(self):
        original = "https://produto.mercadolivre.com.br/MLB-1111111111"
        affiliate = "https://produto.mercadolivre.com.br/MLB-2222222222"
        assert not preserves_product("Mercado Livre", original, affiliate)

    def test_mlb_and_mlbu_are_not_same_product(self):
        original = "MLB5881541102"
        affiliate = "MLBU5881541102"
        assert not preserves_product("Mercado Livre", original, affiliate)


# ============================================================
# MercadoLivreAffiliateProvider.generate()
# ============================================================

class TestAffiliateProviderGenerate:

    @pytest.fixture
    def config_with_template(self):
        return StoreAffiliateConfig(
            affiliate_id="TEST123",
            template="https://www.mercadolivre.com.br/{product_id}?af={affiliate_id}",
        )

    @pytest.fixture
    def config_with_map(self):
        return StoreAffiliateConfig(
            affiliate_id="TEST123",
            mapping="MLB5881541102=https://meli.la/mL1;MLBU3401120243=https://meli.la/mL2",
        )

    def test_extracts_mlb_for_template(self, config_with_template):
        provider = MercadoLivreAffiliateProvider(config_with_template)
        url = "https://produto.mercadolivre.com.br/MLB-5881541102"
        affiliate_url, source, error = provider.generate(url)
        assert error == ""
        assert "MLB5881541102" in affiliate_url
        assert source == "official_template"

    def test_extracts_mlbu_for_template(self, config_with_template):
        provider = MercadoLivreAffiliateProvider(config_with_template)
        url = "https://www.mercadolivre.com.br/up/MLBU3401120243"
        affiliate_url, source, error = provider.generate(url)
        assert error == ""
        assert "MLBU3401120243" in affiliate_url
        # Confirmar que o U nao foi removido
        assert "MLB3401120243" not in affiliate_url.replace("MLBU", "___")
        assert source == "official_template"

    def test_mlbu_preserved_in_product_id(self, config_with_template):
        provider = MercadoLivreAffiliateProvider(config_with_template)
        url = "https://www.mercadolivre.com.br/up/MLBU3401120243"
        affiliate_url, source, error = provider.generate(url)
        assert "MLBU3401120243" in affiliate_url
        assert "MLB3401120243" not in affiliate_url or "MLBU" in affiliate_url

    def test_official_map_mlb(self, config_with_map):
        provider = MercadoLivreAffiliateProvider(config_with_map)
        url = "https://produto.mercadolivre.com.br/MLB-5881541102"
        affiliate_url, source, error = provider.generate(url)
        assert error == ""
        assert affiliate_url == "https://meli.la/mL1"
        assert source == "official_map"

    def test_official_map_mlbu(self, config_with_map):
        provider = MercadoLivreAffiliateProvider(config_with_map)
        url = "https://www.mercadolivre.com.br/up/MLBU3401120243"
        affiliate_url, source, error = provider.generate(url)
        assert error == ""
        assert affiliate_url == "https://meli.la/mL2"
        assert source == "official_map"

    def test_texto_contendo_mlb(self, config_with_template):
        provider = MercadoLivreAffiliateProvider(config_with_template)
        url = "texto qualquer com MLB-5881541102 no meio"
        affiliate_url, _, error = provider.generate(url)
        assert error == ""
        assert "MLB5881541102" in affiliate_url

    def test_texto_contendo_mlbu(self, config_with_template):
        provider = MercadoLivreAffiliateProvider(config_with_template)
        url = "texto qualquer com MLBU-3401120243 no meio"
        affiliate_url, _, error = provider.generate(url)
        assert error == ""
        assert "MLBU3401120243" in affiliate_url