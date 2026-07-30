from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.affiliates.manager import AffiliateManager
from src.promotion_hunter.collectors.shopee_keyword import ShopeeKeywordCollector
from src.promotion_hunter.contracts import PromotionSource
from src.promotion_hunter.normalization import ProductNormalizer
from src.promotion_hunter.registry import CollectorRegistry
from src.promotion_hunter.runner import PromotionHunterRunner
from tests.promotion_hunter.fakes import FakeCollector, FakePipeline


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


def source(store="Shopee", keyword="ssd"):
    return PromotionSource(
        "test-source", "keyword", store, "Teste",
        {"keyword": keyword}, limit=5,
    )


def test_collector_rejects_non_keyword():
    collector = ShopeeKeywordCollector(FakeAdapter())
    src = PromotionSource("s", "url", "Shopee", "Teste")
    with pytest.raises(ValueError, match="somente fontes do tipo keyword"):
        collector.collect(src)


def test_collector_rejects_non_shopee_store():
    collector = ShopeeKeywordCollector(FakeAdapter())
    src = PromotionSource("s", "keyword", "Mercado Livre", "Teste", {"keyword": "x"})
    with pytest.raises(ValueError, match="somente Shopee"):
        collector.collect(src)


def test_collector_returns_products():
    adapter = FakeAdapter(products=[{"loja": "Shopee", "titulo": "SSD", "id": "123.456"}])
    collector = ShopeeKeywordCollector(adapter)
    result = collector.collect(source())
    assert result.status == "success"
    assert len(result.products) == 1


def test_collector_returns_zero_results():
    adapter = FakeAdapter(products=[])
    collector = ShopeeKeywordCollector(adapter)
    result = collector.collect(source())
    assert result.status == "zero_results"


def test_collector_passes_limit():
    adapter = FakeAdapter()
    collector = ShopeeKeywordCollector(adapter)
    src = source(keyword="ssd")
    collector.collect(src)
    assert adapter.last_term == "ssd"
    assert adapter.last_limit == 5


def test_registry_resolves_shopee():
    registry = CollectorRegistry()
    collector = FakeCollector()
    registry.register("Shopee", "keyword", collector)
    result = registry.resolve(PromotionSource("s", "keyword", "Shopee", "Teste"))
    assert result is collector


def test_duas_urls_equivalentes_mesma_identidade():
    normalizer = ProductNormalizer()
    src = PromotionSource("s", "keyword", "Shopee", "Teste", {"keyword": "ssd"})
    pa = {"loja": "Shopee", "titulo": "SSD", "preco": "299,99",
          "link": "https://shopee.com.br/produto-i.123456.789?tracking=1", "id": "123456.789"}
    pb = {"loja": "Shopee", "titulo": "SSD", "preco": "299,99",
          "link": "https://shopee.com.br/product/123456/789", "id": "123456.789"}
    na = normalizer.normalize(pa, src)
    nb = normalizer.normalize(pb, src)
    assert na.deduplication_key == nb.deduplication_key
    assert "shopee" in na.deduplication_key
    assert "123456.789" in na.deduplication_key


def test_identidade_composta_shop_id_item_id():
    normalizer = ProductNormalizer()
    src = PromotionSource("s", "keyword", "Shopee", "Teste", {"keyword": "ssd"})
    p = {"loja": "Shopee", "titulo": "SSD", "preco": "299,99",
         "link": "https://shopee.com.br/produto-i.123456.789", "id": "123456.789"}
    n = normalizer.normalize(p, src)
    assert n.external_id == "123456.789"
    assert n.deduplication_key == "shopee:123456.789"


def test_produto_sem_id_fallback_url():
    normalizer = ProductNormalizer()
    src = PromotionSource("s", "keyword", "Shopee", "Teste", {"keyword": "ssd"})
    p = {"loja": "Shopee", "titulo": "SSD", "preco": "299,99",
         "link": "https://shopee.com.br/produto-i.123456.789"}
    n = normalizer.normalize(p, src)
    assert n.deduplication_key is not None
    assert "shopee" in n.deduplication_key


def test_preco_anterior_presente_preservado():
    normalizer = ProductNormalizer()
    src = PromotionSource("s", "keyword", "Shopee", "Teste", {"keyword": "ssd"})
    p = {"loja": "Shopee", "titulo": "SSD", "preco": "299,99", "id": "123.456",
         "link": "https://shopee.com.br/produto-i.123.456", "preco_antigo": "399,99", "previous_price": "399,99"}
    n = normalizer.normalize(p, src)
    assert n.previous_price is not None
    assert n.previous_price > n.current_price


def test_preco_anterior_ausente_nao_inventado():
    normalizer = ProductNormalizer()
    src = PromotionSource("s", "keyword", "Shopee", "Teste", {"keyword": "ssd"})
    p = {"loja": "Shopee", "titulo": "SSD", "preco": "299,99", "id": "123.456",
         "link": "https://shopee.com.br/produto-i.123.456"}
    n = normalizer.normalize(p, src)
    assert n.previous_price is None


def test_duplicidade_entre_ciclos():
    normalizer = ProductNormalizer()
    s1 = PromotionSource("s1", "keyword", "Shopee", "C1", {"keyword": "ssd"})
    s2 = PromotionSource("s2", "keyword", "Shopee", "C2", {"keyword": "ssd"})
    p = {"loja": "Shopee", "titulo": "SSD", "preco": "299,99", "id": "123.456",
         "link": "https://shopee.com.br/produto-i.123.456"}
    n1 = normalizer.normalize(p, s1)
    n2 = normalizer.normalize(p, s2)
    assert n1.deduplication_key == n2.deduplication_key
    merged = n1.merge_provenance(n2)
    assert "s1" in merged.source_ids
    assert "s2" in merged.source_ids


def test_live_delivery_desativado():
    registry = CollectorRegistry()
    registry.register("Shopee", "keyword", FakeCollector())
    pipeline = FakePipeline()
    repository = MagicMock()
    repository.migrate = MagicMock()
    repository.start_run = MagicMock()
    repository.upsert_source = MagicMock()
    repository.record_source_run = MagicMock()
    repository.record_decisions = MagicMock()
    repository.finish_run = MagicMock()
    repository.sent_count_since = MagicMock(return_value=0)
    repository.last_sent_at = MagicMock(return_value=None)
    repository.start_attempt = MagicMock()
    repository.finish_attempt = MagicMock()
    repository.recover = MagicMock()
    from src.promotion_hunter.delivery import DeliveryPolicy, PromotionHunterQueue
    policy = DeliveryPolicy(max_products_per_keyword=5, max_messages_per_run=0)
    queue = PromotionHunterQueue(repository, policy.duplicate_window_hours)
    from src.promotion_hunter.service import PromotionHunterService
    service = PromotionHunterService(registry, pipeline, repository)
    runner = PromotionHunterRunner(service, queue, repository, policy, delivery=None)
    sources = (PromotionSource("s", "keyword", "Shopee", "Teste", {"keyword": "ssd"}),)
    result = runner.run_once(sources, mode="analysis_only")
    assert result.sent == 0
    assert result.mode == "analysis_only"


def test_url_comum_nao_aceita_como_afiliada():
    config = MagicMock()
    config.shopee = MagicMock()
    config.shopee.mapping = None
    config.shopee.template = None
    config.shopee.affiliate_id = None
    config.cache_path = ":memory:"
    config.cache_ttl_hours = 24
    manager = AffiliateManager(config=config, cache=MagicMock())
    result = manager.resolve("Shopee", "https://shopee.com.br/produto-i.123.456")
    assert not result.valid


def test_link_afiliado_valido_aceito():
    config = MagicMock()
    config.shopee = MagicMock()
    config.shopee.affiliate_id = "vivi"
    config.shopee.template = "https://s.shopee.com.br/{affiliate_id}?url={url}"
    config.shopee.mapping = None
    config.cache_path = ":memory:"
    config.cache_ttl_hours = 24
    manager = AffiliateManager(config=config, cache=MagicMock())
    result = manager.resolve("Shopee", "https://shopee.com.br/produto-i.123.456")
    assert result.status == "GENERATED"
    assert result.valid
    assert "vivi" in result.affiliate_url


def test_produto_sem_link_indisponivel():
    config = MagicMock()
    config.shopee = MagicMock()
    config.shopee.affiliate_id = None
    config.shopee.mapping = None
    config.shopee.template = None
    config.cache_path = ":memory:"
    config.cache_ttl_hours = 24
    manager = AffiliateManager(config=config, cache=MagicMock())
    result = manager.resolve("Shopee", "https://shopee.com.br/produto-i.123.456")
    assert not result.valid
    assert result.error is not None


def test_mercado_livre_registry_resolve_unchanged():
    registry = CollectorRegistry()
    collector = FakeCollector()
    registry.register("Mercado Livre", "keyword", collector)
    result = registry.resolve(PromotionSource("s", "keyword", "Mercado Livre", "Teste"))
    assert result is collector


def test_amazon_registry_resolve_unchanged():
    registry = CollectorRegistry()
    collector = FakeCollector()
    registry.register("Amazon", "keyword", collector)
    result = registry.resolve(PromotionSource("s", "keyword", "Amazon", "Teste"))
    assert result is collector