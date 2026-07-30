from types import SimpleNamespace

import pytest

from src.promotion_hunter.decision_mapper import DecisionMapper
from src.promotion_hunter.models import DecisionStatus, NormalizedProduct


def product(source_id):
    return NormalizedProduct(
        "mercado livre:1", "Mercado Livre", "Produto",
        source_ids=(source_id,),
    )


def item(**changes):
    values = {
        "score": 81.5,
        "classification": "boa",
        "filter_approved": True,
        "duplicate": False,
        "operational_blocks": (),
        "queue_status": "queued",
        "reason": "oferta_aprovada",
    }
    values.update(changes)
    return SimpleNamespace(
        run_id="pipeline",
        diagnostic=SimpleNamespace(**values),
        analysis=None,
        error="",
    )


def test_score_and_decision_do_not_change_with_product_origin():
    mapper = DecisionMapper()
    first = mapper.map(product("keyword"), item())
    second = mapper.map(product("category"), item())
    assert first.status == second.status == DecisionStatus.APPROVED
    assert first.score == second.score == 81.5
    assert first.classification == second.classification == "boa"


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"reason": "desconto_insuficiente", "filter_approved": False},
         DecisionStatus.DISCARDED),
        ({"reason": "preco_sem_historico", "filter_approved": False},
         DecisionStatus.PENDING),
        ({"reason": "duplicidade", "duplicate": True},
         DecisionStatus.DISCARDED),
    ],
)
def test_mapper_only_translates_pipeline_result(changes, expected):
    assert DecisionMapper().map(product("source"), item(**changes)).status == expected


def test_approved_without_blocks_keeps_approval_reason():
    decision = DecisionMapper().map(product("source"), item())
    assert decision.status is DecisionStatus.APPROVED
    assert decision.reason == "oferta_aprovada"


def test_affiliate_block_is_pending_and_explains_final_state():
    decision = DecisionMapper().map(product("source"), item(
        operational_blocks=("link_afiliado_ausente",),
    ))
    assert decision.status is DecisionStatus.PENDING
    assert decision.reason == "link_afiliado_ausente"
    assert decision.delivery_payload["operational_blocks"] == (
        "link_afiliado_ausente",
    )


def test_duplicate_is_discarded_with_deterministic_reason():
    decision = DecisionMapper().map(product("source"), item(
        duplicate=True,
        operational_blocks=("link_afiliado_ausente",),
    ))
    assert decision.status is DecisionStatus.DISCARDED
    assert decision.reason == "duplicidade_ativa"


def test_multiple_pending_blocks_use_documented_priority():
    decision = DecisionMapper().map(product("source"), item(
        operational_blocks=(
            "categoria_invalida",
            "link_afiliado_ausente",
            "imagem_ausente",
        ),
    ))
    assert decision.status is DecisionStatus.PENDING
    assert decision.reason == "imagem_ausente"


def test_technical_error_is_sanitized_and_never_approved():
    pipeline_item = item()
    pipeline_item.error = "  falha   técnica \n controlada  "
    decision = DecisionMapper().map(product("source"), pipeline_item)
    assert decision.status is DecisionStatus.PENDING
    assert decision.reason == "falha técnica controlada"
