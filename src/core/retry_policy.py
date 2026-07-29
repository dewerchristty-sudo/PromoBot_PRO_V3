from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
import os
import re

import requests


class RetryDisposition(StrEnum):
    TEMPORARY = "temporario"
    DEFINITIVE = "definitivo"
    UNCERTAIN = "incerto"


@dataclass(frozen=True, slots=True)
class RetryClassification:
    disposition: RetryDisposition
    reason: str


@dataclass(frozen=True, slots=True)
class TransactionalRetryPolicy:
    enabled: bool = False
    max_attempts: int = 5
    delays_minutes: tuple[int, ...] = (1, 5, 15, 30)
    batch_size: int = 10

    DEFAULT_MAX_ATTEMPTS = 5
    DEFAULT_DELAYS = (1, 5, 15, 30)
    DEFAULT_BATCH_SIZE = 10
    TEMPORARY_HTTP_STATUSES = frozenset({408, 429, 500, 502, 503, 504})

    @classmethod
    def from_environment(cls):
        return cls(
            enabled=cls.boolean(
                os.getenv("ENABLE_TRANSACTIONAL_RETRY"),
                False,
            ),
            max_attempts=cls.positive_integer(
                os.getenv("TRANSACTIONAL_RETRY_MAX_ATTEMPTS"),
                cls.DEFAULT_MAX_ATTEMPTS,
            ),
            delays_minutes=cls.positive_delays(
                os.getenv("TRANSACTIONAL_RETRY_DELAYS_MINUTES"),
                cls.DEFAULT_DELAYS,
            ),
            batch_size=cls.positive_integer(
                os.getenv("TRANSACTIONAL_RETRY_BATCH_SIZE"),
                cls.DEFAULT_BATCH_SIZE,
            ),
        )

    def delay_after_attempt(self, attempt_number):
        index = max(int(attempt_number), 1) - 1
        return self.delays_minutes[min(index, len(self.delays_minutes) - 1)]

    def next_attempt_at(self, attempt_number, now=None):
        now = self.aware(now or datetime.now(timezone.utc))
        return now + timedelta(
            minutes=self.delay_after_attempt(attempt_number)
        )

    def can_retry(self, attempts):
        return int(attempts) < self.max_attempts

    def classify(self, error):
        status = self.http_status(error)
        if status in self.TEMPORARY_HTTP_STATUSES:
            return RetryClassification(
                RetryDisposition.TEMPORARY,
                f"HTTP {status} temporario.",
            )
        if status in {400, 401, 403, 404, 405, 409, 410, 415, 422}:
            return RetryClassification(
                RetryDisposition.DEFINITIVE,
                f"HTTP {status} definitivo.",
            )
        if isinstance(error, (requests.Timeout, TimeoutError)):
            return RetryClassification(
                RetryDisposition.TEMPORARY,
                "Timeout temporario.",
            )
        if isinstance(error, requests.ConnectionError):
            return RetryClassification(
                RetryDisposition.TEMPORARY,
                "Falha temporaria de conexao.",
            )

        text = f"{type(error).__name__}: {error}".casefold()
        if any(marker in text for marker in (
            "connection refused",
            "conexao recusada",
            "temporarily unavailable",
            "indisponibilidade temporaria",
            "network is unreachable",
        )):
            return RetryClassification(
                RetryDisposition.TEMPORARY,
                "Falha temporaria de rede.",
            )
        if any(marker in text for marker in (
            "resposta perdida",
            "resultado indeterminado",
            "resultado externo indeterminado",
            "estado incerto",
            "aceito externamente",
            "accepted externally",
        )):
            return RetryClassification(
                RetryDisposition.UNCERTAIN,
                "Resultado externo indeterminado.",
            )
        if any(marker in text for marker in (
            "destino invalido",
            "destino inválido",
            "invalid destination",
            "autenticacao invalida",
            "autenticação inválida",
            "invalid authentication",
            "credencial ausente",
            "missing credential",
            "payload invalido",
            "payload inválido",
            "invalid payload",
            "formato de destino",
            "validation",
            "validacao local",
            "validação local",
        )):
            return RetryClassification(
                RetryDisposition.DEFINITIVE,
                "Erro permanente de configuracao ou validacao.",
            )
        return RetryClassification(
            RetryDisposition.DEFINITIVE,
            "Erro desconhecido tratado como definitivo.",
        )

    @staticmethod
    def http_status(error):
        response = getattr(error, "response", None)
        status = getattr(response, "status_code", None)
        if status is not None:
            try:
                return int(status)
            except (TypeError, ValueError):
                return None
        match = re.search(r"\bHTTP\s*(408|429|500|502|503|504)\b", str(error), re.I)
        return int(match.group(1)) if match else None

    @staticmethod
    def boolean(value, default=False):
        if value is None:
            return bool(default)
        normalized = str(value).strip().casefold()
        if normalized in {"1", "true", "yes", "on", "sim"}:
            return True
        if normalized in {"0", "false", "no", "off", "nao", "não"}:
            return False
        return bool(default)

    @staticmethod
    def positive_integer(value, default):
        try:
            parsed = int(str(value).strip())
        except (TypeError, ValueError):
            return int(default)
        return parsed if parsed > 0 else int(default)

    @staticmethod
    def positive_delays(value, default):
        if value is None:
            return tuple(default)
        try:
            parsed = tuple(
                int(item.strip())
                for item in str(value).split(",")
            )
        except (TypeError, ValueError):
            return tuple(default)
        if not parsed or any(item <= 0 for item in parsed):
            return tuple(default)
        return parsed

    @staticmethod
    def aware(value):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
