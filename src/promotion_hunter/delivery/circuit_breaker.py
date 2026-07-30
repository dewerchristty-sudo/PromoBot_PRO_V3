"""Circuit breaker para o Promotion Hunter.

Protege contra falhas consecutivas de entrega, suspendendo novas
tentativas após MAX_CONSECUTIVE_FAILURES falhas e aguardando
FAILURE_COOLDOWN_MINUTES antes de tentar novamente.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum

from ..config import (
    FAILURE_COOLDOWN_MINUTES,
    MAX_CONSECUTIVE_FAILURES,
)


class CircuitState(str, Enum):
    CLOSED = "closed"       # Funcionamento normal
    OPEN = "open"           # Bloqueado após falhas consecutivas
    HALF_OPEN = "half_open" # Tentativa de recuperação


@dataclass
class CircuitBreakerState:
    state: CircuitState = CircuitState.CLOSED
    consecutive_failures: int = 0
    opened_at: datetime | None = None
    last_failure_reason: str = ""
    recovery_attempts: int = 0


# Erros que CONTAM como falha do circuit breaker
DELIVERY_FAILURE_PATTERNS = (
    "notifier",
    "whatsapp",
    "desconectado",
    "qr code",
    "grupo nao encontrado",
    "timeout",
    "navegador",
    "confirmacao",
    "destino invalido",
    "evolution",
    "connection",
    "http",
    "send",
    "delivery",
)

# Erros que NÃO contam como falha (bloqueios de política)
NON_FAILURE_PATTERNS = (
    "live_delivery",
    "destino_nao_configurado",
    "fora_do_horario",
    "limite_execucao",
    "limite_hora",
    "limite_sessao",
    "limite_dia",
    "intervalo_minimo",
    "duplicidade",
    "cooldown",
    "score",
    "categoria",
    "modo_",
    "trava_live",
    "max_messages",
)


def _is_delivery_failure(error_message: str) -> bool:
    """Determina se um erro representa falha real de entrega."""
    text = str(error_message or "").strip().casefold()
    if not text:
        return False
    # Verificar padrões de não-falha primeiro (bloqueios de política)
    for pattern in NON_FAILURE_PATTERNS:
        if pattern in text:
            return False
    # Depois verificar padrões de falha real
    for pattern in DELIVERY_FAILURE_PATTERNS:
        if pattern in text:
            return True
    # Erro desconhecido: considerar como falha por segurança
    return True


def _sanitize_error(error_message: str) -> str:
    """Remove dados sensíveis da mensagem de erro."""
    import re
    text = str(error_message or "")
    # Remover números de telefone (padrão internacional)
    text = re.sub(r"\b\d{10,15}\b", "***", text)
    # Remover tokens/keys
    text = re.sub(r"(?i)\b[a-z0-9]{32,}\b", "***", text)
    return text[:200]


class CircuitBreaker:
    def __init__(self, clock=None):
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._state = CircuitBreakerState()

    @property
    def state(self):
        return self._state.state

    @property
    def is_open(self):
        return self._state.state == CircuitState.OPEN

    @property
    def is_closed(self):
        return self._state.state == CircuitState.CLOSED

    def allow_delivery(self) -> tuple[bool, str]:
        """Verifica se uma entrega pode prosseguir."""
        state = self._state
        now = self._clock()

        if state.state == CircuitState.CLOSED:
            return True, "circuit_closed"

        if state.state == CircuitState.HALF_OPEN:
            if state.recovery_attempts > 0:
                return False, "circuit_breaker_open"
            return True, "half_open_recovery_attempt"

        # OPEN state
        if state.opened_at is None:
            return False, "circuit_breaker_open"

        cooldown = timedelta(minutes=FAILURE_COOLDOWN_MINUTES)
        if now - state.opened_at >= cooldown:
            # Transição para HALF_OPEN
            state.state = CircuitState.HALF_OPEN
            state.recovery_attempts = 0
            return True, "half_open_recovery_attempt"

        return False, "circuit_breaker_open"

    def record_success(self):
        """Registra entrega bem-sucedida — fecha o circuito."""
        state = self._state
        state.state = CircuitState.CLOSED
        state.consecutive_failures = 0
        state.opened_at = None
        state.last_failure_reason = ""
        state.recovery_attempts = 0

    def record_failure(self, error_message: str):
        """Registra falha de entrega e atualiza o estado."""
        state = self._state
        if not _is_delivery_failure(error_message):
            return  # Não conta como falha de entrega

        state.consecutive_failures += 1
        state.last_failure_reason = _sanitize_error(error_message)

        if state.state == CircuitState.HALF_OPEN:
            # Falha na tentativa de recuperação → reabre
            state.state = CircuitState.OPEN
            state.opened_at = self._clock()
            state.recovery_attempts = 1

        if state.state == CircuitState.CLOSED and state.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
            state.state = CircuitState.OPEN
            state.opened_at = self._clock()