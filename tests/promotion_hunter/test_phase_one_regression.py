from types import SimpleNamespace

from src.promotion_hunter.contracts import PromotionSource
from src.promotion_hunter.decision_mapper import DecisionMapper
from src.promotion_hunter.models import DecisionStatus
from src.promotion_hunter.normalization import ProductNormalizer
from src.promotion_hunter.adapters.offer_pipeline import (
    PromotionHunterOfferPipelineAdapter,
)
from src.offers.models import OfferCandidate


PHASE_ONE_PRICES = ("1.040", "1.199", "1.125", "1.357", "1.357")


def pipeline_item(product, duplicate=False):
    return SimpleNamespace(
        run_id="pipeline",
        error="",
        analysis=SimpleNamespace(
            candidate=SimpleNamespace(
                title=product.title,
                store=product.store,
                current_price=product.current_price,
                previous_price=None,
                image_url=product.image_url,
                affiliate_link="",
                product_link=product.url,
            ),
            score=SimpleNamespace(
                total=15,
                classification="oferta_fraca_sem_evidencia",
            ),
        ),
        diagnostic=SimpleNamespace(
            score=15,
            classification="oferta_fraca_sem_evidencia",
            filter_approved=True,
            duplicate=duplicate,
            operational_blocks=("link_afiliado_ausente",),
            queue_status="blocked",
            reason="oferta_aprovada",
        ),
    )


def test_phase_one_products_reach_pipeline_with_correct_prices_and_reasons():
    source = PromotionSource(
        "keyword-1", "keyword", "Mercado Livre", "ssd 1tb",
        {"keyword": "ssd 1tb"}, limit=5,
    )
    normalizer = ProductNormalizer()
    products = tuple(
        normalizer.normalize({
            "id": f"MLB{index}",
            "loja": "Mercado Livre",
            "titulo": f"SSD {index}",
            "preco": price,
            "link": f"https://produto.mercadolivre.com.br/MLB-{index}",
            "imagem": f"https://image/{index}",
        }, source)
        for index, price in enumerate(PHASE_ONE_PRICES, start=1)
    )
    assert [item.current_price for item in products] == [
        1040, 1199, 1125, 1357, 1357,
    ]
    pipeline_candidates = tuple(
        OfferCandidate.from_mapping(
            PromotionHunterOfferPipelineAdapter._canonical_payload(
                item.pipeline_payload()
            )
        )
        for item in products
    )
    assert [item.current_price for item in pipeline_candidates] == [
        1040, 1199, 1125, 1357, 1357,
    ]
    assert len({item.deduplication_key for item in products}) == 5

    decisions = tuple(
        DecisionMapper().map(
            product,
            pipeline_item(product, duplicate=index == 5),
        )
        for index, product in enumerate(products, start=1)
    )
    assert [item.status for item in decisions[:4]] == [
        DecisionStatus.PENDING,
    ] * 4
    assert [item.reason for item in decisions[:4]] == [
        "link_afiliado_ausente",
    ] * 4
    assert decisions[4].status is DecisionStatus.DISCARDED
    assert decisions[4].reason == "duplicidade_ativa"
    assert not any(
        item.status is DecisionStatus.APPROVED for item in decisions
    )
