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
