from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .models import DecisionStatus


@dataclass(frozen=True)
class PromotionHunterCycleResult:
    mode: str
    run_id: str
    collected: int
    unique: int
    approved: int
    discarded: int
    pending: int
    queued: int
    sent: int
    blocked: int
    errors: tuple[str, ...]


class PromotionHunterRunner:
    MODES = {"dry_run", "analysis_only", "live"}

    def __init__(self, service, queue, repository, policy,
                 delivery=None, clock=None):
        self.service = service
        self.queue = queue
        self.repository = repository
        self.policy = policy
        self.delivery = delivery
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.execution_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.session_sent = 0
        self.queue.recover()

    def start(self):
        self.stop_event.clear()

    def stop(self):
        self.stop_event.set()

    def run_once(self, sources, mode="analysis_only"):
        if mode not in self.MODES:
            raise ValueError("Modo inválido")
        if not self.execution_lock.acquire(blocking=False):
            raise RuntimeError("Já existe um ciclo do Promotion Hunter ativo")
        try:
            result = self.service.run(sources)
            products = {
                item.deduplication_key: item
                for item in result.normalized_products
            }
            approved = [
                decision for decision in result.decisions
                if decision.status is DecisionStatus.APPROVED
            ]
            discarded = sum(
                item.status is DecisionStatus.DISCARDED
                for item in result.decisions
            )
            pending = sum(
                item.status is DecisionStatus.PENDING
                for item in result.decisions
            )
            queued = 0
            sent = blocked = 0
            errors = []

            if mode == "live":
                live_enabled = os.getenv(
                    "PROMOTION_HUNTER_LIVE_DELIVERY", "false"
                ).strip().casefold() in {"1", "true", "yes", "on"}
                destination = (
                    getattr(self.delivery, "destination", "")
                    if self.delivery else ""
                )
                can_deliver = (
                    live_enabled
                    and destination
                    and self.policy.max_messages_per_run > 0
                )
                if can_deliver:
                    for decision in approved:
                        product = products[decision.product_key]
                        if self.queue.enqueue(result.run_id, product, decision):
                            queued += 1
                    sent, blocked, errors = self._deliver_pending()
                else:
                    blocked = len(approved)
                    if not live_enabled:
                        errors = ("live_delivery_desativado",)
                    elif not destination:
                        errors = ("destino_nao_configurado",)
                    else:
                        errors = ("max_messages_zero",)
            else:
                blocked = len(approved)
            return PromotionHunterCycleResult(
                mode, result.run_id, result.collected_count,
                result.unique_count, len(approved), discarded, pending,
                queued, sent, blocked, tuple(errors),
            )
        finally:
            self.execution_lock.release()

    def _deliver_pending(self):
        now = self.clock()
        hour_since = (now - timedelta(hours=1)).isoformat()
        run_sent = sent = blocked = 0
        errors = []
        live_enabled = os.getenv(
            "PROMOTION_HUNTER_LIVE_DELIVERY", "false"
        ).strip().casefold() in {"1", "true", "yes", "on"}
        destination = getattr(self.delivery, "destination", "") if self.delivery else ""
        for item in self.queue.pending():
            if self.stop_event.is_set():
                blocked += 1
                continue
            decision = self.policy.evaluate(
                mode="live", live_enabled=live_enabled,
                destination=destination, now=now, run_sent=run_sent,
                hour_sent=self.repository.sent_count_since(hour_since),
                session_sent=self.session_sent,
                last_sent_at=self.repository.last_sent_at(),
            )
            if not decision.allowed:
                blocked += 1
                errors.append(decision.reason)
                continue
            started = now.isoformat()
            attempt_id = self.repository.start_attempt(item["id"], started)
            success, error = self.delivery.send(item)
            finished = self.clock().isoformat()
            self.repository.finish_attempt(
                item["id"], attempt_id,
                "sent" if success else "failed", finished, error,
            )
            if success:
                sent += 1
                run_sent += 1
                self.session_sent += 1
            else:
                errors.append(error)
        return sent, blocked, errors
