from collections.abc import Callable
import re
from typing import Any

from src.core.delivery_models import (
    DeliveryStatus,
    DestinationDelivery,
    DestinationDeliveryResult,
    mask_delivery_destination,
)


class DeliveryService:
    """Executa uma entrega isolada sem conhecer Notifier ou transportes."""

    def __init__(self, repository, retry_policy=None):
        self.repository = repository
        self.retry_policy = retry_policy

    def deliver(
        self,
        delivery: DestinationDelivery,
        send: Callable[[], Any],
        record_history: Callable[[], None] | None = None,
        sanitized_metadata: dict | None = None,
    ) -> DestinationDeliveryResult:
        stored, _created = self.repository.create(delivery)
        masked = mask_delivery_destination(stored.destination)

        if stored.status == DeliveryStatus.SENT:
            return self.result(
                stored,
                masked,
                sent=False,
                already_sent=True,
            )

        if stored.status != DeliveryStatus.PENDING:
            return self.result(
                stored,
                masked,
                error=(
                    "Entrega nao executada: estado atual "
                    f"{stored.status.value}."
                ),
            )

        attempt = self.repository.start_attempt(
            stored.id,
            sanitized_metadata=sanitized_metadata,
        )
        try:
            transport_result = send()
        except Exception as error:
            safe_error = self.safe_error(error, stored.destination)
            if self.retry_policy is not None and self.retry_policy.enabled:
                classification = self.retry_policy.classify(error)
                failed = self.repository.finish_reserved_failure(
                    stored.id,
                    classification.disposition,
                    safe_error,
                    self.retry_policy,
                )
            else:
                failed = self.repository.finish_attempt(
                    stored.id,
                    DeliveryStatus.FAILED,
                    error=safe_error,
                    temporary_error=None,
                )
            return self.result(
                failed,
                masked,
                attempt_number=attempt.attempt_number,
                error=safe_error,
            )

        external_id = self.external_id(transport_result)
        sent = self.repository.finish_attempt(
            stored.id,
            DeliveryStatus.SENT,
            external_id=external_id,
        )
        history_error = ""
        if record_history is not None:
            try:
                record_history()
            except Exception as error:
                # O transporte ja confirmou sucesso. Uma falha no historico
                # legado nao pode transformar a entrega em falha nem reenviar.
                history_error = self.safe_error(error, stored.destination)

        return self.result(
            sent,
            masked,
            attempt_number=attempt.attempt_number,
            sent=True,
            external_id=external_id,
            history_error=history_error,
        )

    @staticmethod
    def result(
        delivery,
        masked_destination,
        attempt_number=0,
        sent=False,
        already_sent=False,
        error="",
        external_id="",
        history_error="",
    ):
        return DestinationDeliveryResult(
            delivery_id=delivery.id,
            delivery_key=delivery.delivery_key,
            publication_key=delivery.publication_key,
            channel=delivery.channel,
            masked_destination=masked_destination,
            status=delivery.status,
            attempt_number=int(attempt_number),
            sent=bool(sent),
            already_sent=bool(already_sent),
            error=str(error or ""),
            external_id=str(external_id or ""),
            history_error=str(history_error or ""),
        )

    @staticmethod
    def external_id(result):
        if isinstance(result, dict):
            for key in ("id", "messageId", "message_id", "key"):
                value = result.get(key)
                if isinstance(value, dict):
                    value = value.get("id")
                if value:
                    return str(value)[:500]
        return ""

    @staticmethod
    def safe_error(error, destination=""):
        text = f"{type(error).__name__}: {error}"
        destination = str(destination or "")
        if destination:
            text = text.replace(
                destination,
                mask_delivery_destination(destination),
            )
        text = re.sub(
            r"(?i)\b(api[-_ ]?key|token|password|senha|authorization|"
            r"cookie|secret)\b\s*[:=]\s*[^,;\s]+",
            r"\1=[REMOVIDO]",
            text,
        )
        text = re.sub(
            r"(?i)\b(https?://)([^/@\s:]+):([^/@\s]+)@",
            r"\1[REMOVIDO]@",
            text,
        )
        text = re.sub(
            r"(?i)\b(payload|body|headers?)\b\s*[:=]\s*"
            r"(\{.*?\}|\[.*?\]|[^;]+)",
            r"\1=[REMOVIDO]",
            text,
        )
        text = re.sub(
            r"\b[A-Za-z0-9+/]{120,}={0,2}\b",
            "[BASE64_REMOVIDO]",
            text,
        )
        return " ".join(text.split())[:1000]
