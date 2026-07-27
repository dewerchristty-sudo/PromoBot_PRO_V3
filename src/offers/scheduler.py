from datetime import datetime, timedelta, timezone
from uuid import uuid4

from .identity import OfferIdentity
from .models import (
    OfferCandidate,
    OfferIdentityResult,
    RankedOffer,
    SchedulerDecision,
    ScoreResult,
    SkippedOffer,
)
from .policy import OfferAnalysisPolicy, OfferSchedulerPolicy
from .queue import OfferQueue
from .ranking import OfferRanking
from src.stores.active import is_active_store


class OfferScheduler:
    """Seleciona e audita ofertas; nunca chama canais de envio."""

    def __init__(
        self,
        queue: OfferQueue,
        policy: OfferSchedulerPolicy | None = None,
        worker_id: str = "shadow-scheduler",
    ):
        self.queue = queue
        self.repository = queue.repository
        self.policy = policy or OfferSchedulerPolicy()
        self.worker_id = worker_id
        self.ranking = OfferRanking(OfferAnalysisPolicy(
            ranking_max_per_category=self.policy.ranking_max_per_category,
            ranking_max_per_store=self.policy.ranking_max_per_store,
            ranking_max_per_identity=self.policy.ranking_max_per_identity,
        ))

    def run(self, now: datetime | None = None) -> SchedulerDecision:
        now = self.normalize_datetime(now or datetime.now(timezone.utc))
        run_id = uuid4().hex
        reasons: list[str] = []
        skipped: list[SkippedOffer] = []

        self.queue.release_expired_reservations(now)
        self.queue.expire_due(now)
        all_items = [
            item for item in self.queue.list(limit=5000)
            if is_active_store(item.store)
        ]
        for item in all_items:
            if item.status in {"blocked", "expired"}:
                reason = "bloqueado" if item.status == "blocked" else "expirado"
                skipped.append(SkippedOffer(item.id, reason, item.status))

        hourly_used = self.repository.count_selected_since(
            now - timedelta(hours=1)
        )
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        daily_used = self.repository.count_selected_since(day_start)
        hourly_remaining = max(self.policy.max_per_hour - hourly_used, 0)
        daily_remaining = max(self.policy.max_per_day - daily_used, 0)

        if not self.within_hours(now):
            reasons.append("fora_do_horario")
            return self.finish(
                run_id, (), skipped, hourly_remaining, daily_remaining,
                self.next_start(now), reasons, now,
            )
        if hourly_remaining <= 0:
            reasons.append("limite_por_hora")
            return self.finish(
                run_id, (), skipped, 0, daily_remaining,
                now + timedelta(hours=1), reasons, now,
            )
        if daily_remaining <= 0:
            reasons.append("limite_diario")
            return self.finish(
                run_id, (), skipped, hourly_remaining, 0,
                day_start + timedelta(days=1, hours=self.policy.start_hour),
                reasons, now,
            )

        last_selected = self.repository.last_selected_at()
        next_allowed = (
            last_selected + timedelta(minutes=self.policy.minimum_interval_minutes)
            if last_selected
            else None
        )
        if next_allowed and now < next_allowed:
            reasons.append("intervalo_minimo")
            return self.finish(
                run_id, (), skipped, hourly_remaining, daily_remaining,
                next_allowed, reasons, now,
            )

        queued = [
            item for item in all_items
            if item.status == "queued"
            and item.available_at <= now
            and item.expires_at > now
        ]
        eligible = []
        for item in queued:
            if item.score < self.policy.minimum_score:
                skipped.append(
                    SkippedOffer(item.id, "score_insuficiente", item.status)
                )
                self.repository.record_decision(
                    item.id, "skip", "score_insuficiente", run_id
                )
                continue
            eligible.append(item)

        capacity = min(
            self.policy.max_per_hour,
            hourly_remaining,
            daily_remaining,
        )
        ranked = self.ranking.rank(
            [self.as_ranked(item) for item in eligible],
            limit=capacity,
        )
        selected_ids = [int(item.candidate.product_id) for item in ranked]
        selected_id_set = {int(item_id) for item_id in selected_ids}
        for item in eligible:
            if item.id not in selected_id_set:
                skipped.append(
                    SkippedOffer(item.id, "falta_de_diversidade", item.status)
                )
                self.repository.record_decision(
                    item.id, "skip", "falta_de_diversidade", run_id
                )

        reservation_end = now + timedelta(
            minutes=self.policy.reservation_minutes
        )
        reserved = self.repository.reserve_ids(
            selected_ids,
            self.worker_id,
            now,
            reservation_end,
            run_id,
        )
        selected = tuple(
            self.queue.select_shadow(item.id, run_id)
            for item in reserved
        )
        if not selected:
            reasons.append("nenhuma_oferta_elegivel")
        return self.finish(
            run_id,
            selected,
            skipped,
            max(hourly_remaining - len(selected), 0),
            max(daily_remaining - len(selected), 0),
            (
                now + timedelta(minutes=self.policy.minimum_interval_minutes)
                if selected else None
            ),
            reasons,
            now,
        )

    def as_ranked(self, item) -> RankedOffer:
        candidate = OfferCandidate(
            product_id=item.id,
            title=item.title,
            store=item.store,
            category=item.category,
            current_price=item.current_price,
            previous_price=item.previous_price,
            collected_at=item.created_at,
        )
        identity = OfferIdentityResult(
            signature=item.canonical_identity,
            normalized_title=OfferIdentity().normalize_title(item.title),
            canonical_link="",
            link_signature="",
            promotion_signature=item.promotion_signature,
            similarity_signature=item.canonical_identity,
        )
        return RankedOffer(
            candidate=candidate,
            score=ScoreResult(
                total=item.score,
                classification=item.classification,
                components=item.score_components,
                policy_version=1,
                confidence=item.confidence,
            ),
            identity=identity,
        )

    def finish(
        self,
        run_id,
        selected,
        skipped,
        hourly_remaining,
        daily_remaining,
        next_allowed_at,
        reasons,
        now,
    ):
        for item in skipped:
            if item.reason in {"bloqueado", "expirado"}:
                self.repository.record_decision(
                    item.queue_item_id,
                    "skip",
                    item.reason,
                    run_id,
                )
        decision = SchedulerDecision(
            run_id=run_id,
            selected_offers=tuple(selected),
            skipped_offers=tuple(skipped),
            selected_count=len(selected),
            hourly_remaining=hourly_remaining,
            daily_remaining=daily_remaining,
            next_allowed_at=next_allowed_at,
            reasons=tuple(reasons),
        )
        self.repository.record_scheduler_run(
            run_id,
            decision.selected_count,
            hourly_remaining,
            daily_remaining,
            reasons,
            now,
        )
        return decision

    def within_hours(self, now):
        hour = now.hour
        start = self.policy.start_hour
        end = self.policy.end_hour
        if start == end:
            return True
        if start < end:
            return start <= hour < end
        return hour >= start or hour < end

    def next_start(self, now):
        candidate = now.replace(
            hour=self.policy.start_hour,
            minute=0,
            second=0,
            microsecond=0,
        )
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate

    @staticmethod
    def normalize_datetime(value):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
