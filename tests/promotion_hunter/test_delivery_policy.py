from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

import pytest

from src.promotion_hunter.delivery.policy import DeliveryPolicy

BRT = ZoneInfo("America/Sao_Paulo")
UTC = timezone.utc


def evaluate_at_utc(hour, minute, second=0, **overrides):
    """Avalia a policy com um horário UTC específico."""
    now = datetime(2026, 7, 30, hour, minute, second, tzinfo=UTC)
    params = {
        "mode": "live",
        "live_enabled": True,
        "destination": "5511999999999",
        "now": now,
        "run_sent": 0,
        "hour_sent": 0,
        "session_sent": 0,
        "last_sent_at": None,
        **overrides,
    }
    return DeliveryPolicy().evaluate(**params)


def evaluate_at_brt(hour, minute, second=0, **overrides):
    """Avalia a policy com um horário BRT (America/Sao_Paulo)."""
    now = datetime(2026, 7, 30, hour, minute, second, tzinfo=BRT)
    params = {
        "mode": "live",
        "live_enabled": True,
        "destination": "5511999999999",
        "now": now,
        "run_sent": 0,
        "hour_sent": 0,
        "session_sent": 0,
        "last_sent_at": None,
        **overrides,
    }
    return DeliveryPolicy().evaluate(**params)


# =====================================================================
# Testes com horário UTC convertido para BRT (UTC-3)
# =====================================================================

def test_0759_brt_blocked_via_utc():
    """10:59 UTC = 07:59 BRT → bloqueado."""
    result = evaluate_at_utc(10, 59, 59)
    assert not result.allowed
    assert result.reason == "fora_do_horario"


def test_0800_brt_allowed_via_utc():
    """11:00 UTC = 08:00 BRT → permitido."""
    result = evaluate_at_utc(11, 0, 0)
    assert result.allowed
    assert result.reason == "permitido"


def test_1200_brt_allowed_via_utc():
    """15:00 UTC = 12:00 BRT → permitido."""
    result = evaluate_at_utc(15, 0, 0)
    assert result.allowed


def test_1900_brt_allowed_via_utc():
    """22:00 UTC = 19:00 BRT → permitido."""
    result = evaluate_at_utc(22, 0, 0)
    assert result.allowed


def test_2159_brt_allowed_via_utc():
    """00:59 UTC (dia 31) = 21:59 BRT (dia 30) → permitido."""
    now = datetime(2026, 7, 31, 0, 59, 59, tzinfo=UTC)
    result = DeliveryPolicy().evaluate(
        mode="live", live_enabled=True, destination="5511999999999",
        now=now, run_sent=0, hour_sent=0, session_sent=0, last_sent_at=None,
    )
    assert result.allowed


def test_2200_brt_blocked_via_utc():
    """01:00 UTC (dia 31) = 22:00 BRT (dia 30) → bloqueado."""
    now = datetime(2026, 7, 31, 1, 0, 0, tzinfo=UTC)
    result = DeliveryPolicy().evaluate(
        mode="live", live_enabled=True, destination="5511999999999",
        now=now, run_sent=0, hour_sent=0, session_sent=0, last_sent_at=None,
    )
    assert not result.allowed
    assert result.reason == "fora_do_horario"


# =====================================================================
# Testes direto com timezone BRT
# =====================================================================

def test_0759_brt_direct_blocked():
    result = evaluate_at_brt(7, 59, 59)
    assert not result.allowed
    assert result.reason == "fora_do_horario"


def test_0800_brt_direct_allowed():
    result = evaluate_at_brt(8, 0, 0)
    assert result.allowed
    assert result.reason == "permitido"


def test_1147_brt_direct_allowed():
    """Horário real do primeiro teste live (11:47 BRT)."""
    result = evaluate_at_brt(11, 47, 0)
    assert result.allowed


def test_1930_brt_direct_allowed():
    result = evaluate_at_brt(19, 30, 0)
    assert result.allowed


def test_2130_brt_direct_allowed():
    result = evaluate_at_brt(21, 30, 0)
    assert result.allowed


def test_2159_brt_direct_allowed():
    result = evaluate_at_brt(21, 59, 59)
    assert result.allowed


def test_2200_brt_direct_blocked():
    result = evaluate_at_brt(22, 0, 0)
    assert not result.allowed
    assert result.reason == "fora_do_horario"


def test_2230_brt_direct_blocked():
    result = evaluate_at_brt(22, 30, 0)
    assert not result.allowed


# =====================================================================
# Datetime naive
# =====================================================================

def test_datetime_naive_raises():
    with pytest.raises(ValueError, match="naive"):
        DeliveryPolicy().within_window(datetime(2026, 7, 30, 12, 0, 0))


# =====================================================================
# Outras políticas (não regrediram)
# =====================================================================

def test_live_disabled_blocks():
    result = evaluate_at_brt(12, 0, live_enabled=False)
    assert not result.allowed
    assert result.reason == "trava_live_desativada"


def test_no_destination_blocks():
    result = evaluate_at_brt(12, 0, destination="")
    assert not result.allowed
    assert result.reason == "destino_pessoal_ausente"


def test_dry_run_blocks():
    result = evaluate_at_brt(12, 0, mode="dry_run")
    assert not result.allowed


def test_analysis_only_blocks():
    result = evaluate_at_brt(12, 0, mode="analysis_only")
    assert not result.allowed