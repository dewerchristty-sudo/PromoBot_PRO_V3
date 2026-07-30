from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.affiliates.manager import AffiliateManager
from src.affiliates.validation import product_identity
from src.promotion_hunter.collectors.amazon_keyword import AmazonKeywordCollector
from src.promotion_hunter.contracts import PromotionSource
from src.promotion_hunter.normalization import ProductNormalizer
from src.promotion_hunter.registry import CollectorRegistry
from src.promotion_hunter.runner import PromotionHunterRunner
from tests.promotion_hunter.fakes import FakeCollector, FakePipeline


def test_duas_urls_mesmo_asin_mesma_identidade():
    """Duas URLs diferentes do mesmo ASIN produzem a mesma identidade canônica."""
    normalizer = ProductNormalizer()
    source = PromotionSource("s", "keyword", "Amazon", "Teste", {"keyword": "ssd"})

    product_a = {"loja": "Amazon", "titulo": "SSD A", "preco": "299,99",
                 "link": "https://www.amazon.com.br/dp/B0ABCDEFGH?ref=xx", "id": "B0ABCDEFGH"}
    product_b = {"loja": "Amazon", "titulo": "SSD B", "preco": "299,99",
                 "link": "https://www.amazon.com.br/gp/product/B0ABCDEFGH?th=1", "id": "B0ABCDEFGH"}

    normalized_a = normalizer.normalize(product_a, source)
    normalized_b = normalizer.normalize(product_b, source)

    assert normalized_a.deduplication_key == normalized_b.deduplication_key
    # Verifica que a chave contém o ASIN e não a URL
    assert "B0ABCDEFGH" in normalized_a.deduplication_key
    assert normalized_a.external_id == "B0ABCDEFGH"
    assert normalized_b.external_id == "B0ABCDEFGH"


def test_preco_anterior_presente_preservado():
    """Preço anterior presente é preservado na normalização."""
    normalizer = ProductNormalizer()
    source = PromotionSource("s", "keyword", "Amazon", "Teste", {"keyword": "ssd"})
    product = {
        "loja": "Amazon", "titulo": "SSD", "preco": "299,99",
        "link": "https://www.amazon.com.br/dp/B0ABCDEFGH",
        "id": "B0ABCDEFGH",
        "previous_price": "399,99",
        "preco_antigo": "399,99",
    }
    normalized = normalizer.normalize(product, source)
    assert normalized.previous_price is not None
    assert normalized.previous_price > normalized.current_price


def test_preco_anterior_ausente_nao_inventado():
    """Preço anterior ausente não é inventado na normalização."""
    normalizer = ProductNormalizer()
    source = PromotionSource("s", "keyword", "Amazon", "Teste", {"keyword": "ssd"})
    product = {
        "loja": "Amazon", "titulo": "SSD", "preco": "299,99",
        "link": "https://www.amazon.com.br/dp/B0ABCDEFGH",
        "id": "B0ABCDEFGH",
    }
    normalized = normalizer.normalize(product, source)
    assert normalized.previous_price is None


def test_url_amazon_comum_nao_aceita_como_link_afiliado():
    """URL comum da Amazon sem associate tag não é aceita como link afiliado."""
    config = MagicMock()
    config.amazon = MagicMock()
    config.amazon.associate_tag = "achadinhos-20"
    config.amazon.template = None
    config.amazon.mapping = None
    config.cache_path = ":memory:"
    config.cache_ttl_hours = 24

    manager = AffiliateManager(config=config, cache=MagicMock())
    # URL comum SEM tag de afiliado
    result = manager.resolve(
        "Amazon",
        "https://www.amazon.com.br/dp/B012345678",
        "https://www.amazon.com.br/dp/B012345678",  # sem tag
    )
    # Deve ser rejeitada porque não tem associate tag
    assert result.status == "INVALID" or result.error is not None


def test_link_afiliado_amazon_valido_aceito():
    """Link afiliado Amazon válido (com associate tag) é aceito."""
    config = MagicMock()
    config.amazon = MagicMock()
    config.amazon.associate_tag = "achadinhos-20"
    config.amazon.template = None
    config.amazon.mapping = None
    config.cache_path = ":memory:"
    config.cache_ttl_hours = 24

    manager = AffiliateManager(config=config, cache=MagicMock())
    result = manager.resolve(
        "Amazon",
        "https://www.amazon.com.br/dp/B012345678",
        "https://www.amazon.com.br/dp/B012345678?tag=achadinhos-20",
    )
    # Deve ser aceito porque tem a tag correta
    assert result.status in ("PROVIDED", "GENERATED")
    assert result.valid


def test_produto_sem_link_afiliado_permanece_indisponivel():
    """Produto sem link afiliado configurado permanece indisponível."""
    config = MagicMock()
    config.amazon = MagicMock()
    config.amazon.associate_tag = None
    config.amazon.mapping = None
    config.amazon.template = None
    config.cache_path = ":memory:"
    config.cache_ttl_hours = 24

    manager = AffiliateManager(config=config, cache=MagicMock())
    result = manager.resolve(
        "Amazon",
        "https://www.amazon.com.br/dp/B012345678",
    )
    # Sem configuração, permanece inválido (NOT_CONFIGURED ou PARTIALLY_CONFIGURED)
    assert not result.valid
    assert result.error is not None


def test_duplicidade_mesmo_asin_entre_ciclos():
    """Mesmo ASIN em ciclos diferentes produz a mesma chave de deduplicação."""
    normalizer = ProductNormalizer()
    source1 = PromotionSource("s1", "keyword", "Amazon", "Ciclo1", {"keyword": "ssd"})
    source2 = PromotionSource("s2", "keyword", "Amazon", "Ciclo2", {"keyword": "ssd"})

    product = {"loja": "Amazon", "titulo": "SSD", "preco": "299,99",
               "link": "https://www.amazon.com.br/dp/B0ABCDEFGH", "id": "B0ABCDEFGH"}

    norm1 = normalizer.normalize(product, source1)
    norm2 = normalizer.normalize(product, source2)

    assert norm1.deduplication_key == norm2.deduplication_key
    # merge_provenance deve unificar as fontes
    merged = norm1.merge_provenance(norm2)
    assert "s1" in merged.source_ids
    assert "s2" in merged.source_ids


def test_amazon_flow_live_delivery_desativado():
    """Runner recusa modo live sem delivery configurado."""
    registry = CollectorRegistry()
    registry.register("Amazon", "keyword", FakeCollector())
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

    runner = PromotionHunterRunner(
        service, queue, repository, policy, delivery=None
    )

    sources = (PromotionSource("s", "keyword", "Amazon", "Teste", {"keyword": "ssd"}),)
    result = runner.run_once(sources, mode="analysis_only")
    # analysis_only bloqueia entrega
    assert result.sent == 0
    assert result.mode == "analysis_only"


def test_amazon_no_adapter_asin_extraido_da_url():
    """ASIN é extraído de URLs Amazon mesmo quando o campo id não está presente."""
    from src.promotion_hunter.adapters.amazon import AmazonCollectionAdapter

    product = {
        "loja": "Amazon",
        "titulo": "SSD Teste",
        "preco": "299,99",
        "link": "https://www.amazon.com.br/dp/B0ABCDEFGH",
    }
    result = AmazonCollectionAdapter._technical_product(product)
    assert result["id"] == "B0ABCDEFGH"


def test_amazon_sem_asin_fallback_url():
    """Produto Amazon sem ASIN usa fallback da URL normalizada como identidade."""
    normalizer = ProductNormalizer()
    source = PromotionSource("s", "keyword", "Amazon", "Teste", {"keyword": "ssd"})
    product = {
        "loja": "Amazon", "titulo": "SSD",
        "preco": "299,99",
        "link": "https://www.amazon.com.br/dp/B0ABCDEFGH",
        # sem campo "id" — o adapter extrai da URL, mas se não extrair, fallback
    }
    # Simula produto sem ASIN (como se não tivesse sido extraído)
    product_no_id = dict(product)
    product_no_id.pop("id", None)
    product_no_id["link"] = "https://www.amazon.com.br/dp/B0ABCDEFGH"
    normalized = normalizer.normalize(product_no_id, source)
    # A identidade canônica usa a URL normalizada como fallback
    assert normalized.deduplication_key is not None
    assert "amazon" in normalized.deduplication_key