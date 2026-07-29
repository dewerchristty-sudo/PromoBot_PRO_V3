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


def delivery_publication_key(
    alert_id="",
    original_link="",
    signature="",
    price="",
):
    parts = (
        str(alert_id or "").strip(),
        str(original_link or "").strip(),
        str(signature or "").strip().casefold(),
        str(price or "").strip(),
    )
    if not any(parts):
        raise ValueError("A publicacao precisa de uma identidade.")
    material = "\x1f".join(("promobot-publication-v1", *parts))
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


@dataclass(frozen=True, slots=True)
class DestinationDeliveryResult:
    delivery_id: int
    delivery_key: str
    publication_key: str
    channel: str
    masked_destination: str
    status: DeliveryStatus
    attempt_number: int = 0
    sent: bool = False
    already_sent: bool = False
    error: str = ""
    external_id: str = ""
    history_error: str = ""

    @property
    def completed(self):
        return self.sent or self.already_sent


@dataclass(frozen=True, slots=True)
class DeliveryBatchResult:
    deliveries: tuple[DestinationDeliveryResult, ...] = ()

    def __bool__(self):
        return any(item.completed for item in self.deliveries)

    @property
    def sent_count(self):
        return sum(item.sent for item in self.deliveries)

    @property
    def already_sent_count(self):
        return sum(item.already_sent for item in self.deliveries)

    @property
    def failed_count(self):
        return sum(not item.completed for item in self.deliveries)

    @property
    def completed_publication_keys(self):
        return frozenset(
            item.publication_key
            for item in self.deliveries
            if item.completed
        )

    @property
    def errors(self):
        return tuple(
            item.error for item in self.deliveries
            if item.error
        )

    @property
    def history_errors(self):
        return tuple(
            item.history_error for item in self.deliveries
            if item.history_error
        )


def utc_now():
    return datetime.now(timezone.utc)
