from dataclasses import dataclass
from typing import Any, Callable

from src.core.delivery_models import (
    DeliveryStatus,
    DestinationDeliveryResult,
    mask_delivery_destination,
)
from src.core.delivery_service import DeliveryService


@dataclass(frozen=True, slots=True)
class RetryExecution:
    send: Callable[[], Any]
    record_history: Callable[[], None] | None = None
    sanitized_metadata: dict | None = None


class TransactionalRetryService:
    def __init__(self, repository, policy):
        self.repository = repository
        self.policy = policy

    def process_due(self, execution_resolver, now=None):
        if not self.policy.enabled:
            return ()
        due = self.repository.list_due_retries(
            now=now,
            max_attempts=self.policy.max_attempts,
            limit=self.policy.batch_size,
        )
        results = []
        for delivery in due:
            reserved = self.repository.reserve_retry(
                delivery.id,
                now=now,
                max_attempts=self.policy.max_attempts,
            )
            if reserved is None:
                continue
            try:
                execution = execution_resolver(delivery)
                self.repository.update_attempt_metadata(
                    reserved.id,
                    execution.sanitized_metadata,
                )
                transport_result = execution.send()
            except Exception as error:
                classification = self.policy.classify(error)
                safe_error = DeliveryService.safe_error(
                    error,
                    delivery.destination,
                )
                final = self.repository.finish_reserved_failure(
                    delivery.id,
                    classification.disposition,
                    safe_error,
                    self.policy,
                    now=now,
                )
                results.append(self.result(
                    final,
                    attempt_number=reserved.attempt_number,
                    error=safe_error,
                ))
                continue

            external_id = DeliveryService.external_id(transport_result)
            sent = self.repository.finish_attempt(
                delivery.id,
                DeliveryStatus.SENT,
                external_id=external_id,
            )
            history_error = ""
            if (
                execution.record_history is not None
                and not self.repository.history_exists(sent)
            ):
                try:
                    execution.record_history()
                except Exception as error:
                    history_error = DeliveryService.safe_error(
                        error,
                        delivery.destination,
                    )
            results.append(self.result(
                sent,
                attempt_number=reserved.attempt_number,
                sent=True,
                external_id=external_id,
                history_error=history_error,
            ))
        return tuple(results)

    def prepare_manual_retry(
        self,
        delivery_id,
        *,
        confirm_definitive=False,
        now=None,
    ):
        return self.repository.prepare_manual_retry(
            delivery_id,
            confirm_definitive=confirm_definitive,
            now=now,
        )

    @staticmethod
    def result(
        delivery,
        *,
        attempt_number=0,
        sent=False,
        error="",
        external_id="",
        history_error="",
    ):
        return DestinationDeliveryResult(
            delivery_id=delivery.id,
            delivery_key=delivery.delivery_key,
            publication_key=delivery.publication_key,
            channel=delivery.channel,
            masked_destination=mask_delivery_destination(
                delivery.destination
            ),
            status=delivery.status,
            attempt_number=attempt_number,
            sent=sent,
            error=error,
            external_id=external_id,
            history_error=history_error,
        )
