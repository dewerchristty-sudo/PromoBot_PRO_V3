from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import re


class DeliveryStatus(StrEnum):
    PENDING = "pendente"
    SENDING = "enviando"
    SENT = "enviado"
    FAILED = "falhou"
    WAITING_RETRY = "aguardando_nova_tentativa"
    DEFINITIVE_FAILURE = "falha_definitiva"
    REVIEW_REQUIRED = "revisao_necessaria"


class InvalidDeliveryTransition(ValueError):
    pass


DELIVERY_TRANSITIONS = {
    DeliveryStatus.PENDING: frozenset({
        DeliveryStatus.SENDING,
        DeliveryStatus.DEFINITIVE_FAILURE,
        DeliveryStatus.REVIEW_REQUIRED,
    }),
    DeliveryStatus.SENDING: frozenset({
        DeliveryStatus.SENT,
        DeliveryStatus.FAILED,
        DeliveryStatus.REVIEW_REQUIRED,
    }),
    DeliveryStatus.FAILED: frozenset({
        DeliveryStatus.WAITING_RETRY,
        DeliveryStatus.DEFINITIVE_FAILURE,
        DeliveryStatus.REVIEW_REQUIRED,
    }),
    DeliveryStatus.WAITING_RETRY: frozenset({
        DeliveryStatus.SENDING,
        DeliveryStatus.DEFINITIVE_FAILURE,
        DeliveryStatus.REVIEW_REQUIRED,
    }),
    DeliveryStatus.REVIEW_REQUIRED: frozenset({
        DeliveryStatus.PENDING,
        DeliveryStatus.DEFINITIVE_FAILURE,
    }),
    DeliveryStatus.SENT: frozenset(),
    DeliveryStatus.DEFINITIVE_FAILURE: frozenset(),
}


def validate_delivery_transition(current, target):
    current = DeliveryStatus(current)
    target = DeliveryStatus(target)
    if target not in DELIVERY_TRANSITIONS[current]:
        raise InvalidDeliveryTransition(
            f"Transicao de entrega invalida: {current.value} -> {target.value}."
        )
    return target


def normalize_delivery_destination(destination):
    value = str(destination or "").strip()
    if not value:
        raise ValueError("O destino da entrega e obrigatorio.")
    if "@" in value:
        return value.casefold()
    digits = re.sub(r"\D", "", value)
    return digits or value.casefold()


def delivery_idempotency_key(publication_key, channel, destination):
    publication = str(publication_key or "").strip()
    normalized_channel = str(channel or "").strip().casefold()
    if not publication:
        raise ValueError("A chave da publicacao e obrigatoria.")
    if not normalized_channel:
        raise ValueError("O canal da entrega e obrigatorio.")
    normalized_destination = normalize_delivery_destination(destination)
    material = "\x1f".join((
        "promobot-delivery-v1",
        publication,
        normalized_channel,
        normalized_destination,
    ))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def mask_delivery_destination(destination):
    normalized = normalize_delivery_destination(destination)
    if "@" in normalized:
        local, domain = normalized.split("@", 1)
        visible = local[-4:] if len(local) > 4 else local[-2:]
        return f"***{visible}@{domain}"
    visible = normalized[-4:] if len(normalized) > 4 else normalized[-2:]
    return f"***{visible}"


@dataclass(frozen=True, slots=True)
class DestinationDelivery:
    id: int | None
    delivery_key: str
    publication_key: str
    channel: str
    destination: str
    status: DeliveryStatus = DeliveryStatus.PENDING
    alert_id: int | None = None
    original_link: str = ""
    signature: str = ""
    decision_origin: str = "legado"
    attempts: int = 0
    next_attempt_at: datetime | None = None
    last_error: str = ""
    temporary_error: bool | None = None
    external_id: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None
    sent_at: datetime | None = None

    @classmethod
    def create(
        cls,
        publication_key,
        channel,
        destination,
        **fields,
    ):
        return cls(
            id=None,
            delivery_key=delivery_idempotency_key(
                publication_key,
                channel,
                destination,
            ),
            publication_key=str(publication_key).strip(),
            channel=str(channel).strip(),
            destination=normalize_delivery_destination(destination),
            **fields,
        )


@dataclass(frozen=True, slots=True)
class DeliveryAttempt:
    id: int | None
    delivery_id: int
    attempt_number: int
    status: DeliveryStatus
    started_at: datetime
    finished_at: datetime | None = None
    error: str = ""
    temporary_error: bool | None = None
    external_id: str = ""
    sanitized_metadata: str = ""


def utc_now():
    return datetime.now(timezone.utc)
