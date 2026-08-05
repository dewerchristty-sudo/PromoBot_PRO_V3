from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .models import DecisionStatus
from .previous_price_enricher import PreviousPriceEnricher
from .delivery.authorization import require_real_delivery_authorized


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
    DELIVERY_BATCH_SIZE = 100

    def __init__(self, service, queue, repository, policy,
                 delivery=None, clock=None, enricher=None, waiter=None):
        self.service = service
        self.queue = queue
        self.repository = repository
        self.policy = policy
        self.delivery = delivery
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.execution_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.waiter = waiter or self.stop_event.wait
        self.session_sent = 0
        self.queue.recover()
        self.enricher = enricher

    def start(self):
        self.stop_event.clear()

    def stop(self):
        self.stop_event.set()

    def run_once(self, sources, mode="analysis_only"):
        if mode == "live":
            require_real_delivery_authorized(
                boundary="PromotionHunterRunner.run_once"
            )
        if mode not in self.MODES:
            raise ValueError("Modo inválido")
        if not self.execution_lock.acquire(blocking=False):
            raise RuntimeError("Já existe um ciclo do Promotion Hunter ativo")
        try:
            if self.enricher is not None:
                self.enricher.reset_count()
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

            if mode == "analysis_only":
                for decision in approved:
                    product = products[decision.product_key]
                    if self.queue.enqueue(result.run_id, product, decision):
                        queued += 1
                # Persist the operational simulation without loading pending
                # rows for delivery or invoking any outbound transport.
                blocked = len(approved) - queued
            elif mode == "live":
                live_enabled = os.getenv(
                    "PROMOTION_HUNTER_LIVE_DELIVERY", "false"
                ).strip().casefold() in {"1", "true", "yes", "on"}
                destination = self._delivery_destination()
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
                    sent, blocked, errors = self._deliver_pending(result.run_id)
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

    def _deliver_pending(self, run_id=None):
        run_sent = sent = blocked = 0
        errors = []
        live_enabled = os.getenv(
            "PROMOTION_HUNTER_LIVE_DELIVERY", "false"
        ).strip().casefold() in {"1", "true", "yes", "on"}
        destination = self._delivery_destination()
        cursor = None
        while not self.stop_event.is_set():
            pending_options = {
                "limit": self.DELIVERY_BATCH_SIZE,
                "after": cursor,
            }
            if run_id is not None:
                pending_options["run_id"] = run_id
            try:
                batch = self.queue.pending(**pending_options)
            except TypeError:
                # Compatibility for injected legacy/test queues. Production
                # PromotionHunterQueue supports the run_id safety boundary.
                pending_options.pop("run_id", None)
                batch = self.queue.pending(**pending_options)
            if not batch:
                break
            for queued_item in batch:
                item = dict(queued_item)
                # Legacy/imported rows and lightweight test doubles may not
                # expose approved_at yet.  The queue itself still returns the
                # canonical field in production; this fallback only keeps the
                # delivery boundary tolerant while migrations are rolling out.
                next_cursor = (
                    item.get("approved_at") or item.get("created_at") or "",
                    item["id"],
                )
                if next_cursor == cursor:
                    return sent, blocked, errors
                cursor = next_cursor
                if self.stop_event.is_set():
                    break
                now = self.clock()
                last_sent_at = self.repository.last_sent_at()
                decision = self._evaluate_delivery_policy(
                    now, last_sent_at, live_enabled, destination, run_sent
                )
                if (
                    not decision.allowed
                    and decision.reason == "intervalo_minimo"
                ):
                    remaining = self._remaining_interval(now, last_sent_at)
                    if remaining > 0 and self.waiter(remaining):
                        break
                    if self.stop_event.is_set():
                        break
                    now = self.clock()
                    last_sent_at = self.repository.last_sent_at()
                    decision = self._evaluate_delivery_policy(
                        now, last_sent_at, live_enabled, destination, run_sent
                    )
                if not decision.allowed:
                    blocked += 1
                    errors.append(decision.reason)
                    return sent, blocked, errors
                # Enriquecer preco_antigo do Mercado Livre antes do envio
                if self.enricher is not None:
                    try:
                        self.enricher.enrich(item)
                    except Exception as exc:
                        errors.append(
                            "previous_price_enrichment: "
                            + " ".join(str(exc).split())[:200]
                        )

                started = now.isoformat()
                attempt_id = self.repository.start_attempt(item["id"], started)
                completed_loader = getattr(
                    self.repository, "completed_destinations", lambda _id: ()
                )
                completed = completed_loader(item["id"])
                try:
                    delivery_result = self.delivery.send(item, completed)
                except TypeError:
                    delivery_result = self.delivery.send(item)
                success, error = delivery_result
                permanent = bool(getattr(delivery_result, "permanent", False))
                finished = self.clock().isoformat()
                receipt_recorder = getattr(
                    self.repository, "record_destination_results", None
                )
                destination_results = getattr(
                    delivery_result, "destination_results", ()
                )
                if receipt_recorder and destination_results:
                    receipt_recorder(
                        item["id"], item.get("product_key", ""), attempt_id,
                        destination_results,
                    )
                self.repository.finish_attempt(
                    item["id"], attempt_id,
                    "sent" if success else "failed", finished, error,
                    permanent,
                )
                if success:
                    sent += 1
                    run_sent += 1
                    self.session_sent += 1
                else:
                    errors.append(error)
        return sent, blocked, errors

    def _delivery_destination(self):
        if not self.delivery:
            return ""
        available = getattr(self.delivery, "has_destination", None)
        if available is not None:
            return "category-routing" if bool(available) else ""
        return str(getattr(self.delivery, "destination", "") or "")

    def _evaluate_delivery_policy(
        self, now, last_sent_at, live_enabled, destination, run_sent
    ):
        hour_since = (now - timedelta(hours=1)).isoformat()
        return self.policy.evaluate(
            mode="live", live_enabled=live_enabled,
            destination=destination, now=now, run_sent=run_sent,
            hour_sent=self.repository.sent_count_since(hour_since),
            session_sent=self.session_sent,
            last_sent_at=last_sent_at,
        )

    def _remaining_interval(self, now, last_sent_at):
        if not last_sent_at:
            return 0.0
        last = datetime.fromisoformat(last_sent_at)
        elapsed = (now - last).total_seconds()
        interval_seconds = (
            float(self.policy.minimum_interval_seconds)
            if self.policy.minimum_interval_seconds is not None
            else float(self.policy.minimum_interval_minutes) * 60
        )
        return max(0.0, interval_seconds - elapsed)
