from datetime import datetime, timedelta, timezone

import pytest

from src.promotion_hunter.delivery.circuit_breaker import (
    CircuitBreaker,
    CircuitState,
    _is_delivery_failure,
    _sanitize_error,
)


def clock_factory(hour=0):
    """Relógio injetável com horário controlado."""
    base = datetime(2026, 7, 30, hour, 0, 0, tzinfo=timezone.utc)
    return lambda: base


def test_starts_closed():
    cb = CircuitBreaker()
    assert cb.is_closed
    assert not cb.is_open


def test_one_failure_keeps_closed():
    cb = CircuitBreaker()
    cb.record_failure("whatsapp desconectado")
    assert cb.is_closed


def test_two_failures_keep_closed():
    cb = CircuitBreaker()
    cb.record_failure("notifier timeout")
    cb.record_failure("whatsapp erro de envio")
    assert cb.is_closed


def test_third_failure_opens():
    cb = CircuitBreaker()
    cb.record_failure("notifier falhou")
    cb.record_failure("whatsapp desconectado")
    cb.record_failure("timeout de entrega")
    assert cb.is_open


def test_open_blocks_notifier():
    cb = CircuitBreaker()
    cb.record_failure("falha1")
    cb.record_failure("falha2")
    cb.record_failure("falha3")
    allowed, reason = cb.allow_delivery()
    assert not allowed
    assert "circuit_breaker_open" in reason


def test_live_false_does_not_count_as_failure():
    cb = CircuitBreaker()
    cb.record_failure("live_delivery_desativado")
    assert cb._state.consecutive_failures == 0
    assert cb.is_closed


def test_destino_vazio_does_not_count():
    cb = CircuitBreaker()
    cb.record_failure("destino_nao_configurado")
    assert cb._state.consecutive_failures == 0


def test_fora_do_horario_does_not_count():
    cb = CircuitBreaker()
    cb.record_failure("fora_do_horario")
    assert cb._state.consecutive_failures == 0


def test_limite_execucao_does_not_count():
    cb = CircuitBreaker()
    cb.record_failure("limite_execucao")
    assert cb._state.consecutive_failures == 0


def test_success_resets_failures():
    cb = CircuitBreaker()
    cb.record_failure("whatsapp falhou")
    cb.record_failure("whatsapp falhou novamente")
    assert cb._state.consecutive_failures == 2
    cb.record_success()
    assert cb._state.consecutive_failures == 0
    assert cb.is_closed


def test_cooldown_not_expired_blocks():
    base = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)
    clock = iter([
        base, base, base,  # 3 falhas
        base,               # verificação após abertura (mesmo minuto)
    ])
    def clock_fn():
        return next(clock)
    cb = CircuitBreaker(clock=clock_fn)
    cb.record_failure("falha1")
    cb.record_failure("falha2")
    cb.record_failure("falha3")
    assert cb.is_open
    allowed, reason = cb.allow_delivery()
    assert not allowed
    assert "circuit_breaker_open" in reason


def test_cooldown_expired_allows_half_open():
    base = datetime(2026, 7, 30, 12, 0, 0, tzinfo=timezone.utc)
    # clock is only called on transitions: 1 call on 3rd failure + 1 on allow_delivery
    clock = iter([
        base,                           # 3rd failure sets opened_at
        base + timedelta(minutes=61),   # allow_delivery after cooldown
    ])
    def clock_fn():
        return next(clock)
    cb = CircuitBreaker(clock=clock_fn)
    cb.record_failure("whatsapp falha1")
    cb.record_failure("whatsapp falha2")
    cb.record_failure("whatsapp falha3")
    allowed, reason = cb.allow_delivery()
    assert allowed
    assert reason == "half_open_recovery_attempt"


def test_half_open_success_closes_circuit():
    cb = CircuitBreaker()
    cb.record_failure("falha1")
    cb.record_failure("falha2")
    cb.record_failure("falha3")
    # Não testamos cooldown aqui, forçamos half_open
    cb._state.state = CircuitState.HALF_OPEN
    cb.record_success()
    assert cb.is_closed
    assert cb._state.consecutive_failures == 0


def test_half_open_failure_reopens():
    cb = CircuitBreaker()
    cb.record_failure("falha1")
    cb.record_failure("falha2")
    cb.record_failure("falha3")
    cb._state.state = CircuitState.HALF_OPEN
    cb.record_failure("notifier falhou na recuperacao")
    assert cb.is_open


def test_single_recovery_attempt():
    cb = CircuitBreaker()
    cb._state.state = CircuitState.HALF_OPEN
    cb._state.recovery_attempts = 1
    allowed, reason = cb.allow_delivery()
    assert not allowed


def test_sanitize_removes_phone():
    result = _sanitize_error("erro no destino 5527996703669")
    assert "5527996703669" not in result


def test_sanitize_removes_token():
    result = _sanitize_error("token abcdef1234567890abcdef1234567890 invalido")
    assert "abcdef1234567890abcdef1234567890" not in result


def test_is_delivery_failure_notifier():
    assert _is_delivery_failure("notifier timeout")


def test_is_not_delivery_failure_policy():
    assert not _is_delivery_failure("fora_do_horario")
    assert not _is_delivery_failure("limite_execucao")