from types import SimpleNamespace

from src.promotion_hunter.adapters.offer_pipeline import (
    InertOfferScheduler,
    PromotionHunterOfferPipelineAdapter,
)
from src.promotion_hunter.contracts import PromotionSource
from src.promotion_hunter.decision_mapper import DecisionMapper
from src.promotion_hunter.normalization import ProductNormalizer
from src.offers.models import OfferCandidate


def test_adapter_forwards_normalized_payload_without_business_recalculation():
    class FakePipeline:
        def __init__(self): self.calls = []; self.closed = False
        def process_batch(self, products):
            self.calls.append(products)
            return SimpleNamespace(items=())
        def close(self): self.closed = True

    pipeline = FakePipeline()
    adapter = PromotionHunterOfferPipelineAdapter(pipeline)
    payload = [{
        "titulo": "Produto",
        "preco": "1.357",
        "preco_atual": 1357.0,
        "preco_antigo": "1.500",
        "preco_anterior": 1500.0,
        "economia": 143.0,
        "desconto_percentual": 9.53,
    }]
    result = adapter.process_batch(payload)
    forwarded = pipeline.calls[0][0]
    assert forwarded["current_price"] == 1357.0
    assert forwarded["previous_price"] == 1500.0
    assert forwarded["savings"] == 143.0
    assert forwarded["discount_percent"] == 9.53
    assert forwarded["raw_price"] == "1.357"
    assert forwarded["raw_previous_price"] == "1.500"
    assert payload[0] == {
        "titulo": "Produto",
        "preco": "1.357",
        "preco_atual": 1357.0,
        "preco_antigo": "1.500",
        "preco_anterior": 1500.0,
        "economia": 143.0,
        "desconto_percentual": 9.53,
    }
    assert result.items == ()
    adapter.close()
    assert pipeline.closed


def test_real_candidate_prefers_normalized_prices_over_raw_metadata():
    cases = (
        ("1.357", 1357.0),
        ("1.199", 1199.0),
        ("1.125", 1125.0),
        ("758", 758.0),
        ("1.357", 1357.0),
    )
    for raw, normalized in cases:
        payload = PromotionHunterOfferPipelineAdapter._canonical_payload({
            "preco": raw,
            "preco_atual": normalized,
            "preco_anterior": None,
            "economia": None,
            "desconto_percentual": None,
        })
        candidate = OfferCandidate.from_mapping(payload)
        assert candidate.current_price == normalized
        if "." in raw:
            assert candidate.current_price != float(raw)
        assert payload["raw_price"] == raw


def test_canonical_payload_handles_absent_raw_and_optional_money_fields():
    original = {
        "titulo": "Produto",
        "preco_atual": 0.0,
        "preco_anterior": None,
        "economia": None,
    }
    payload = PromotionHunterOfferPipelineAdapter._canonical_payload(original)
    assert payload["current_price"] == 0.0
    assert payload["previous_price"] is None
    assert payload["savings"] is None
    assert "raw_price" not in payload
    assert original == {
        "titulo": "Produto",
        "preco_atual": 0.0,
        "preco_anterior": None,
        "economia": None,
    }


def test_canonical_payload_keeps_missing_current_price_invalid():
    payload = PromotionHunterOfferPipelineAdapter._canonical_payload({
        "titulo": "Produto sem preço",
    })
    assert payload["current_price"] is None
    assert OfferCandidate.from_mapping(payload).current_price is None


def test_inert_scheduler_never_selects_or_starts_background_work():
    decision = InertOfferScheduler().run()
    assert decision.selected_count == 0
    assert decision.selected_offers == ()
    assert decision.skipped_offers == ()


def test_canonical_payload_uses_preco_antigo_when_preco_anterior_is_absent():
    """Quando preco_anterior (R) está ausente mas preco_antigo (G) existe,
    o payload canônico deve usar preco_antigo como previous_price."""
    payload = PromotionHunterOfferPipelineAdapter._canonical_payload({
        "titulo": "Armario Madesa",
        "preco": "699,99",
        "preco_atual": 699.99,
        "preco_antigo": "858,81",
    })
    assert payload["previous_price"] == "858,81"
    assert "raw_previous_price" in payload
    assert payload["raw_previous_price"] == "858,81"


def test_canonical_payload_preco_anterior_overrides_preco_antigo():
    """preco_anterior (R) tem precedência sobre preco_antigo (G)."""
    payload = PromotionHunterOfferPipelineAdapter._canonical_payload({
        "titulo": "Produto",
        "preco_atual": 100.0,
        "preco_anterior": 200.0,
        "preco_antigo": "150",
    })
    assert payload["previous_price"] == 200.0


def test_canonical_payload_previous_price_not_overwritten_by_none():
    """Um previous_price válido não pode ser sobrescrito por None."""
    payload = PromotionHunterOfferPipelineAdapter._canonical_payload({
        "titulo": "Produto",
        "preco_atual": 100.0,
        "preco_anterior": None,
        "preco_antigo": "150",
        "previous_price": 180.0,
    })
    assert payload["previous_price"] == 180.0


def test_canonical_payload_previous_price_remains_none_when_all_absent():
    """Sem nenhum preço anterior, previous_price deve permanecer None."""
    payload = PromotionHunterOfferPipelineAdapter._canonical_payload({
        "titulo": "Produto sem desconto",
        "preco_atual": 50.0,
    })
    assert payload["previous_price"] is None


def test_full_flow_maps_mercado_livre_preco_antigo_to_delivery_payload():
    """Regressão: fluxo completo garante que preco_antigo do ML
    chegue ao delivery_payload como previous_price."""
    from src.promotion_hunter.decision_mapper import DecisionMapper
    from src.promotion_hunter.normalization import ProductNormalizer
    import json

    # 1. Normalizar (simulando saida do ML)
    source = PromotionSource("url-1", "product_url", "Mercado Livre", "URL")
    product = ProductNormalizer().normalize({
        "id": "MLBU3401120243",
        "titulo": "Armario Madesa",
        "preco": "699,99",
        "preco_antigo": "858,81",
        "link": "https://www.mercadolivre.com.br/.../MLBU3401120243",
    }, source)

    assert product.previous_price == 858.81
    assert product.current_price == 699.99

    # 2. Payload canônico
    pipeline_payload = product.pipeline_payload()
    canonical = PromotionHunterOfferPipelineAdapter._canonical_payload(
        pipeline_payload
    )
    assert canonical["previous_price"] is not None

    # 3. Simular OfferCandidate (usa OfferScore.number que aceita string ou float)
    from src.offers.score import OfferScore
    previous_num = OfferScore.number(canonical.get("previous_price"))
    assert previous_num == 858.81

    # 4. Mapear para delivery_payload
    candidate = SimpleNamespace(
        title=product.title, store=product.store,
        current_price=product.current_price,
        previous_price=previous_num,
        image_url="", affiliate_link="https://meli.la/test",
        product_link=product.url,
    )
    analysis = SimpleNamespace(
        candidate=candidate,
        score=SimpleNamespace(total=15, classification="fraca"),
    )
    item = SimpleNamespace(
        run_id="test", analysis=analysis, error="",
        diagnostic=SimpleNamespace(
            score=15, classification="fraca", filter_approved=True,
            duplicate=False, operational_blocks=(), queue_status="queued",
            reason="oferta_aprovada",
        ),
    )
    decision = DecisionMapper().map(product, item)
    payload = decision.delivery_payload
    assert payload["previous_price"] == 858.81
    assert payload["current_price"] == 699.99


def test_mapper_preserves_pipeline_affiliate_link_for_delivery():
    product = ProductNormalizer().normalize(
        {
            "id": "MLB1", "titulo": "Produto", "preco": 10,
            "link": "https://original",
        },
        PromotionSource("kw", "keyword", "Mercado Livre", "Busca"),
    )
    candidate = SimpleNamespace(
        title="Produto", store="Mercado Livre", current_price=10,
        previous_price=20, image_url="https://image",
        affiliate_link="https://afiliado", product_link="https://original",
    )
    analysis = SimpleNamespace(
        candidate=candidate,
        score=SimpleNamespace(total=90, classification="excelente"),
    )
    item = SimpleNamespace(
        run_id="pipeline", analysis=analysis, error="",
        diagnostic=SimpleNamespace(
            score=90, classification="excelente", filter_approved=True,
            duplicate=False, operational_blocks=(), queue_status="queued",
            reason="oferta_aprovada",
        ),
    )
    decision = DecisionMapper().map(product, item)
    assert decision.delivery_payload["product_url"] == "https://afiliado"
