from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

class DeliveryFailureKind(str, Enum):
    PERMANENT = "permanent"
    TEMPORARY = "temporary"


@dataclass(frozen=True)
class DestinationDeliveryResult:
    destination: str
    channel: str = ""
    attempted_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    request_made: bool = False
    http_status: int | None = None
    returned_status: str = ""
    evolution_status: str = "nao_enviado"
    accepted: bool = False
    error: str = ""


@dataclass(frozen=True)
class DeliveryResult:
    success: bool
    error: str = ""
    failure_kind: DeliveryFailureKind | None = None
    aggregate_status: str = "falha_total"
    destination_results: tuple[DestinationDeliveryResult, ...] = ()

    @property
    def permanent(self) -> bool:
        return self.failure_kind is DeliveryFailureKind.PERMANENT

    def __iter__(self):
        yield self.success
        yield self.error


_PERMANENT_MESSAGES = (
    "o arquivo recebido nao e uma imagem valida",
    "a url informada nao retornou conteudo de imagem",
    "o arquivo de imagem nao pode ser aberto pelo pillow",
    "destino pessoal invalido",
    "grupo nao autorizado",
    "grupo bloqueado",
    "bloqueado permanentemente",
)
_TEMPORARY_MESSAGES = (
    "timeout",
    "tempo limite",
    "nao foi possivel conectar",
    "temporariamente indisponivel",
    "nao esta conectada",
    "rate limit",
    "too many requests",
)
_TEMPORARY_HTTP = frozenset({408, 429, 500, 502, 503, 504})
_PERMANENT_HTTP = frozenset({400, 401, 403, 404, 405, 410, 415, 422})


def classify_delivery_failure(error: Exception | str) -> DeliveryFailureKind:
    error_type = type(error)
    if error_type.__name__ == "LowResolutionImageError":
        return DeliveryFailureKind.PERMANENT
    if error_type.__name__ in {"Timeout", "ConnectTimeout", "ConnectionError"}:
        return DeliveryFailureKind.TEMPORARY

    message = "".join(
        character for character in unicodedata.normalize(
            "NFKD", str(error or "").casefold()
        )
        if not unicodedata.combining(character)
    )
    message = " ".join(message.split())
    statuses = {
        int(value) for value in re.findall(r"\bhttp\s*(\d{3})\b", message)
    }
    response = getattr(error, "response", None)
    if response is not None and getattr(response, "status_code", None):
        statuses.add(int(response.status_code))
    if statuses & _TEMPORARY_HTTP:
        return DeliveryFailureKind.TEMPORARY
    if statuses & _PERMANENT_HTTP:
        return DeliveryFailureKind.PERMANENT
    if any(token in message for token in _TEMPORARY_MESSAGES):
        return DeliveryFailureKind.TEMPORARY
    if any(token in message for token in _PERMANENT_MESSAGES):
        return DeliveryFailureKind.PERMANENT
    return DeliveryFailureKind.TEMPORARY
