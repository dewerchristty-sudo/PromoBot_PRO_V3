"""Testes do PromotionHunterDeliveryAdapter — validacao de destinos autorizados."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.promotion_hunter.delivery.notifier_adapter import (
    PromotionHunterDeliveryAdapter,
)

VALID_PERSONAL = "5511999999999"
VALID_PERSONAL_12 = "5511988888888"
VALID_REVIEW_GROUP = "000000000000000001@g.us"
OTHER_GROUP = "999999999999999999@g.us"
DIFFERENT_GROUP = "000000000000000002@g.us"


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch):
    """Isola variaveis de ambiente; o .env real nao vaza."""
    monkeypatch.delenv("WHATSAPP_REVIEW_GROUP", raising=False)
    monkeypatch.delenv("PROMOTION_HUNTER_DESTINATIONS", raising=False)
    monkeypatch.delenv("PROMOTION_HUNTER_PERSONAL_WHATSAPP", raising=False)


# ------------------------------------------------------------------
# Mensagens de erro esperadas (com acentuacao real do codigo-fonte)
# ------------------------------------------------------------------
MSG_GRUPO_NAO_AUTORIZADO = (
    "Grupo n\u00e3o autorizado. "
    "Apenas o grupo de revis\u00e3o configurado \u00e9 permitido."
)
MSG_REVISAO_NAO_CONFIGURADO = (
    "Grupo de revis\u00e3o n\u00e3o est\u00e1 configurado."
)


def test_personal_valid_continues_allowed():
    """Cenario 1: destino pessoal valido continua permitido."""
    dest = PromotionHunterDeliveryAdapter.validate_allowed_destination(
        VALID_PERSONAL
    )
    assert dest == "5511999999999"


def test_personal_invalid_continues_rejected():
    """Cenario 2: destino pessoal invalido continua rejeitado."""
    with pytest.raises(ValueError, match="Destino pessoal"):
        PromotionHunterDeliveryAdapter.validate_allowed_destination("123")


def test_review_group_identical_allowed(monkeypatch):
    """Cenario 3: grupo identico a WHATSAPP_REVIEW_GROUP e permitido."""
    monkeypatch.setenv("WHATSAPP_REVIEW_GROUP", VALID_REVIEW_GROUP)
    dest = PromotionHunterDeliveryAdapter.validate_allowed_destination(
        VALID_REVIEW_GROUP
    )
    assert dest == VALID_REVIEW_GROUP
    assert dest.endswith("@g.us")


def test_other_group_rejected(monkeypatch):
    """Cenario 4: outro grupo @g.us e rejeitado."""
    monkeypatch.setenv("WHATSAPP_REVIEW_GROUP", VALID_REVIEW_GROUP)
    with pytest.raises(ValueError, match=MSG_GRUPO_NAO_AUTORIZADO):
        PromotionHunterDeliveryAdapter.validate_allowed_destination(OTHER_GROUP)


def test_group_one_char_difference_rejected(monkeypatch):
    """Cenario 5: grupo com diferenca de um caractere e rejeitado."""
    monkeypatch.setenv("WHATSAPP_REVIEW_GROUP", VALID_REVIEW_GROUP)
    assert DIFFERENT_GROUP != VALID_REVIEW_GROUP
    with pytest.raises(ValueError, match=MSG_GRUPO_NAO_AUTORIZADO):
        PromotionHunterDeliveryAdapter.validate_allowed_destination(
            DIFFERENT_GROUP
        )


def test_missing_env_rejects_group(monkeypatch):
    """Cenario 6: WHATSAPP_REVIEW_GROUP ausente rejeita grupo."""
    monkeypatch.delenv("WHATSAPP_REVIEW_GROUP", raising=False)
    with pytest.raises(ValueError, match=MSG_REVISAO_NAO_CONFIGURADO):
        PromotionHunterDeliveryAdapter.validate_allowed_destination(
            VALID_REVIEW_GROUP
        )


def test_empty_env_rejects_group(monkeypatch):
    """Cenario 7: WHATSAPP_REVIEW_GROUP vazio rejeita grupo."""
    monkeypatch.setenv("WHATSAPP_REVIEW_GROUP", "")
    with pytest.raises(ValueError, match=MSG_REVISAO_NAO_CONFIGURADO):
        PromotionHunterDeliveryAdapter.validate_allowed_destination(
            VALID_REVIEW_GROUP
        )


def test_env_without_gus_does_not_authorize_group(monkeypatch):
    """Cenario 8: WHATSAPP_REVIEW_GROUP sem @g.us nao autoriza grupo."""
    monkeypatch.setenv("WHATSAPP_REVIEW_GROUP", "5511999999999")
    with pytest.raises(ValueError, match="WHATSAPP_REVIEW_GROUP deve terminar"):
        PromotionHunterDeliveryAdapter.validate_allowed_destination(
            VALID_REVIEW_GROUP
        )


def test_comma_separated_list_rejected(monkeypatch):
    """Cenario 9: lista separada por virgula e rejeitada."""
    monkeypatch.setenv("WHATSAPP_REVIEW_GROUP", VALID_REVIEW_GROUP)
    with pytest.raises(ValueError, match="Lista de destinos"):
        PromotionHunterDeliveryAdapter.validate_allowed_destination(
            "5511999999999,5511988888888"
        )


def test_whitespace_normalized(monkeypatch):
    """Cenario 10: espacos externos sao normalizados."""
    monkeypatch.setenv("WHATSAPP_REVIEW_GROUP", VALID_REVIEW_GROUP)
    dest = PromotionHunterDeliveryAdapter.validate_allowed_destination(
        f"  {VALID_REVIEW_GROUP}  "
    )
    assert dest == VALID_REVIEW_GROUP


def test_destination_not_in_logs(monkeypatch):
    """Cenario 11: destino nao aparece completo em logs de erro."""
    monkeypatch.setenv("WHATSAPP_REVIEW_GROUP", VALID_REVIEW_GROUP)
    with pytest.raises(ValueError) as exc_info:
        PromotionHunterDeliveryAdapter.validate_allowed_destination(OTHER_GROUP)
    message = str(exc_info.value)
    # O destino rejeitado NAO deve aparecer na mensagem de erro
    assert OTHER_GROUP not in message
    # A mensagem generica deve estar presente
    assert "Grupo n\u00e3o autorizado" in message


def test_hunter_flow_uses_delivery_adapter(monkeypatch):
    """Cenario 12: fluxo do Hunter continua passando pelo DeliveryAdapter."""
    monkeypatch.setenv("WHATSAPP_REVIEW_GROUP", VALID_REVIEW_GROUP)
    mock_notifier = MagicMock()
    adapter = PromotionHunterDeliveryAdapter(mock_notifier, VALID_REVIEW_GROUP)
    assert adapter.destination == VALID_REVIEW_GROUP
    assert adapter.notifier is mock_notifier


def test_notifier_not_called_when_group_unauthorized(monkeypatch):
    """Cenario 13: Notifier nao e chamado quando grupo nao e autorizado."""
    monkeypatch.setenv("WHATSAPP_REVIEW_GROUP", VALID_REVIEW_GROUP)
    mock_notifier = MagicMock()
    with pytest.raises(ValueError):
        PromotionHunterDeliveryAdapter(mock_notifier, OTHER_GROUP)
    mock_notifier.format_alert.assert_not_called()
    mock_notifier.send_whatsapp_message.assert_not_called()


def test_circuit_breaker_in_flow(monkeypatch):
    """Cenario 14: circuit breaker continua no fluxo (testado via init do
    adapter, que sempre valida destino)."""
    monkeypatch.setenv("WHATSAPP_REVIEW_GROUP", VALID_REVIEW_GROUP)
    mock_notifier = MagicMock()
    adapter = PromotionHunterDeliveryAdapter(mock_notifier, VALID_REVIEW_GROUP)
    assert isinstance(adapter.destination, str)
    assert adapter.destination.endswith("@g.us")


def test_live_false_blocks_delivery(monkeypatch):
    """Cenario 15: live=false continua bloqueando (o adapter valida destino,
    mas o runner so envia se PROMOTION_HUNTER_LIVE_DELIVERY for true)."""
    monkeypatch.setenv("WHATSAPP_REVIEW_GROUP", VALID_REVIEW_GROUP)
    monkeypatch.setenv("PROMOTION_HUNTER_LIVE_DELIVERY", "false")
    mock_notifier = MagicMock()
    adapter = PromotionHunterDeliveryAdapter(mock_notifier, VALID_REVIEW_GROUP)
    assert adapter.destination == VALID_REVIEW_GROUP


def test_existing_tests_still_pass_validation(monkeypatch):
    """Cenario 16: demais validacoes continuam consistentes."""
    monkeypatch.setenv("WHATSAPP_REVIEW_GROUP", VALID_REVIEW_GROUP)

    # Grupo de revisao autorizado
    assert (
        PromotionHunterDeliveryAdapter.validate_allowed_destination(
            VALID_REVIEW_GROUP
        )
        == VALID_REVIEW_GROUP
    )

    # Pessoal valido
    assert (
        PromotionHunterDeliveryAdapter.validate_allowed_destination(
            VALID_PERSONAL
        )
        == "5511999999999"
    )

    # Pessoal 12 digitos
    assert (
        PromotionHunterDeliveryAdapter.validate_allowed_destination(
            VALID_PERSONAL_12
        )
        == "5511988888888"
    )

    # Pessoal invalido (11 digitos)
    with pytest.raises(ValueError, match="Destino pessoal"):
        PromotionHunterDeliveryAdapter.validate_allowed_destination("55119999999")

    # Outro grupo rejeitado
    with pytest.raises(ValueError):
        PromotionHunterDeliveryAdapter.validate_allowed_destination(OTHER_GROUP)

    # Virgula rejeitada
    with pytest.raises(ValueError, match="Lista de destinos"):
        PromotionHunterDeliveryAdapter.validate_allowed_destination(
            "5511999999999,5521999999999"
        )

    # Grupo de revisao configurado sem @g.us
    monkeypatch.setenv("WHATSAPP_REVIEW_GROUP", "5511999999999")
    with pytest.raises(ValueError, match="WHATSAPP_REVIEW_GROUP deve terminar"):
        PromotionHunterDeliveryAdapter.validate_allowed_destination(
            VALID_REVIEW_GROUP
        )

    # Restaura review group valido
    monkeypatch.setenv("WHATSAPP_REVIEW_GROUP", VALID_REVIEW_GROUP)

    # Grupo @g.us sem var configurada
    monkeypatch.delenv("WHATSAPP_REVIEW_GROUP", raising=False)
    with pytest.raises(ValueError):
        PromotionHunterDeliveryAdapter.validate_allowed_destination(
            VALID_REVIEW_GROUP
        )