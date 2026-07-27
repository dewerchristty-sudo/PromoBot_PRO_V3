from dataclasses import dataclass, replace
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import time
from typing import Any, Mapping
from uuid import uuid4

from src.database.offer_pipeline_repository import OfferPipelineRepository
from src.affiliates import AffiliateManager

from .duplicates import DuplicateChecker
from .history import OfferHistory
from .models import (
    DuplicateCheckResult,
    QueueOffer,
    RankedOffer,
)
from .policy import OfferAnalysisPolicy, OfferSchedulerPolicy
from .queue import OfferQueue
from .scheduler import OfferScheduler
from .service import OfferAnalysis, OfferIntelligenceService
from .score import OfferScore
from .readiness import OfferReadinessEnricher
from src.stores.active import filter_active_products


@dataclass(frozen=True, slots=True)
class OfferDiagnostic:
    title: str
    identity_status: str
    canonical_identity: str
    history_samples: int
    historical_minimum: float
    current_price: float
    score: float
    classification: str
    duplicate: bool
    duplicate_type: str
    filter_approved: bool
    operational_blocks: tuple[str, ...]
    queue_status: str
    scheduler_status: str
    reason: str

    def as_dict(self):
        return {
            field: getattr(self, field)
            for field in self.__dataclass_fields__
        }


@dataclass(frozen=True, slots=True)
class OfferPipelineItemResult:
    run_id: str
    analysis: OfferAnalysis | None
    queue_item: QueueOffer | None
    diagnostic: OfferDiagnostic
    scheduler_status: str
    processing_ms: float
    error: str
    created_at: datetime
    shadow_mode: bool = True
    affects_current_flow: bool = False


@dataclass(frozen=True, slots=True)
class OfferPipelineMetrics:
    run_id: str
    received_count: int
    valid_count: int
    discarded_count: int
    duplicate_count: int
    blocked_count: int
    approved_count: int
    queued_count: int
    selected_shadow_count: int
    average_score: float
    average_processing_ms: float
    stage_timings_ms: Mapping[str, float]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class OfferPipelineBatchResult:
    run_id: str
    items: tuple[OfferPipelineItemResult, ...]
    scheduler_decision: Any
    metrics: OfferPipelineMetrics
    shadow_mode: bool = True
    affects_current_flow: bool = False


class OfferPipeline:
    """Observador do fluxo real; falhas nunca retornam ao StoreManager."""

    def __init__(
        self,
        repository: OfferPipelineRepository,
        service: OfferIntelligenceService | None = None,
        queue: OfferQueue | None = None,
        scheduler: OfferScheduler | None = None,
        affiliate_manager: AffiliateManager | None = None,
    ):
        self.repository = repository
        self.analysis_policy = OfferIntelligenceService.policy_from_environment()
        self.scheduler_policy = self.scheduler_policy_from_environment()
        self.service = service or OfferIntelligenceService(
            history=OfferHistory(
                store=repository,
                policy=self.analysis_policy,
            ),
            duplicate_checker=DuplicateChecker(policy=self.analysis_policy),
            analysis_policy=self.analysis_policy,
        )
        self.queue = queue or OfferQueue(repository, self.scheduler_policy)
        self.affiliate_manager = affiliate_manager or AffiliateManager()
        self.readiness = OfferReadinessEnricher(self.affiliate_manager)
        self.scheduler = scheduler or OfferScheduler(
            self.queue,
            self.scheduler_policy,
            worker_id="real-collection-shadow",
        )
        self.loggers = {
            name: logging.getLogger(f"promobot.{name}")
            for name in (
                "OfferPipeline", "OfferScore", "OfferQueue",
                "OfferScheduler", "OfferRanking", "OfferHistory",
                "OfferIdentity",
            )
        }

    @classmethod
    def from_environment(cls):
        path = Path(
            os.getenv("OFFER_SHADOW_DB_PATH", "offer_shadow.db")
            or "offer_shadow.db"
        )
        repository = OfferPipelineRepository(path)
        repository.migrate()
        return cls(repository)

    @staticmethod
    def enabled():
        return os.getenv(
            "OFFER_SHADOW_PIPELINE_ENABLED",
            "True",
        ).strip().casefold() in {"1", "true", "yes", "on"}

    def close(self):
        try:
            self.affiliate_manager.close()
        finally:
            self.repository.close()

    def process_batch(
        self,
        products: list[Mapping[str, Any]],
        now: datetime | None = None,
    ) -> OfferPipelineBatchResult:
        products = filter_active_products(products)
        now = self.normalize_datetime(now or datetime.now(timezone.utc))
        run_id = uuid4().hex
        batch_start = time.perf_counter()
        stage_totals = {
            "analysis": 0.0,
            "queue": 0.0,
            "scheduler": 0.0,
            "persistence": 0.0,
        }
        results: list[OfferPipelineItemResult] = []

        for product in products:
            item_start = time.perf_counter()
            analysis = None
            queue_item = None
            error = ""
            try:
                product = self.readiness.prepare(product).product
                started = time.perf_counter()
                analysis = self.service.analyze(product, now)
                stage_totals["analysis"] += self.elapsed_ms(started)
                self.loggers["OfferScore"].info(
                    "score=%.2f classification=%s components=%r",
                    analysis.score.total,
                    analysis.score.classification,
                    dict(analysis.score.components),
                )

                started = time.perf_counter()
                operational = list(analysis.filtering.operational_blocks)
                if analysis.duplicate and analysis.duplicate.is_duplicate:
                    operational.append("duplicidade_ativa")
                queue_item, _created = self.queue.enqueue_ranked(
                    RankedOffer(
                        candidate=analysis.candidate,
                        score=analysis.score,
                        identity=analysis.identity,
                        duplicate=analysis.duplicate,
                        history=analysis.history,
                    ),
                    operational,
                )
                if not analysis.filtering.approved and queue_item.status == "queued":
                    queue_item = self.queue.discard(
                        queue_item.id,
                        "; ".join(analysis.filtering.reasons)
                        or "filtro_reprovado",
                    )
                self.service.duplicate_checker.remember(
                    analysis.identity,
                    OfferScore.number(analysis.candidate.current_price),
                    now,
                )
                stage_totals["queue"] += self.elapsed_ms(started)
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                self.loggers["OfferPipeline"].exception(
                    "Falha isolada ao analisar produto: %s",
                    product.get("titulo", product.get("title", "")),
                )

            diagnostic = self.make_diagnostic(
                product,
                analysis,
                queue_item,
                "",
                error,
            )
            results.append(OfferPipelineItemResult(
                run_id=run_id,
                analysis=analysis,
                queue_item=queue_item,
                diagnostic=diagnostic,
                scheduler_status="",
                processing_ms=round(self.elapsed_ms(item_start), 3),
                error=error,
                created_at=now,
            ))

        started = time.perf_counter()
        try:
            decision = self.scheduler.run(now)
        except Exception as exc:
            decision = None
            self.loggers["OfferScheduler"].exception(
                "Falha isolada no scheduler sombra: %s",
                exc,
            )
        stage_totals["scheduler"] += self.elapsed_ms(started)

        selected_ids = {
            item.id for item in (
                decision.selected_offers if decision else ()
            )
        }
        skipped = {
            item.queue_item_id: item.reason
            for item in (decision.skipped_offers if decision else ())
        }
        finalized = []
        for result in results:
            queue_id = result.queue_item.id if result.queue_item else None
            scheduler_status = (
                "selected_shadow"
                if queue_id in selected_ids
                else skipped.get(queue_id, "")
            )
            stored_queue = (
                self.repository.get(queue_id) if queue_id is not None else None
            )
            diagnostic = self.make_diagnostic(
                {},
                result.analysis,
                stored_queue or result.queue_item,
                scheduler_status,
                result.error,
            )
            finalized.append(replace(
                result,
                queue_item=stored_queue or result.queue_item,
                diagnostic=diagnostic,
                scheduler_status=scheduler_status,
            ))

        metrics = self.calculate_metrics(
            run_id,
            finalized,
            decision,
            stage_totals,
            now,
        )
        started = time.perf_counter()
        self.repository.record_pipeline_run(metrics)
        for result in finalized:
            self.repository.record_pipeline_item(result)
        stage_totals["persistence"] += self.elapsed_ms(started)
        metrics = replace(
            metrics,
            stage_timings_ms={
                **stage_totals,
                "total": round(self.elapsed_ms(batch_start), 3),
            },
        )
        self.repository.record_pipeline_run(metrics)
        self.loggers["OfferPipeline"].info(
            "run=%s received=%d queued=%d selected_shadow=%d avg_score=%.2f "
            "avg_ms=%.3f",
            run_id,
            metrics.received_count,
            metrics.queued_count,
            metrics.selected_shadow_count,
            metrics.average_score,
            metrics.average_processing_ms,
        )
        return OfferPipelineBatchResult(
            run_id=run_id,
            items=tuple(finalized),
            scheduler_decision=decision,
            metrics=metrics,
        )

    def make_diagnostic(
        self,
        product,
        analysis,
        queue_item,
        scheduler_status,
        error,
    ):
        title = (
            analysis.candidate.title
            if analysis else str(
                product.get("titulo", product.get("title", "")) or ""
            )
        )
        history = analysis.history if analysis else None
        duplicate = analysis.duplicate if analysis else None
        reason = error
        if not reason and scheduler_status:
            reason = scheduler_status
        if not reason and analysis:
            reason = (
                "oferta_aprovada"
                if analysis.filtering.approved
                else "; ".join(analysis.filtering.reasons)
            )
        return OfferDiagnostic(
            title=title,
            identity_status="OK" if analysis and analysis.identity else "ERRO",
            canonical_identity=(
                analysis.identity.signature
                if analysis and analysis.identity else ""
            ),
            history_samples=history.sample_count if history else 0,
            historical_minimum=history.minimum if history else 0,
            current_price=(
                OfferScore.number(analysis.candidate.current_price)
                if analysis else 0
            ),
            score=analysis.score.total if analysis else 0,
            classification=(
                analysis.score.classification if analysis else "erro"
            ),
            duplicate=bool(duplicate and duplicate.is_duplicate),
            duplicate_type=duplicate.duplicate_type if duplicate else "",
            filter_approved=bool(
                analysis and analysis.filtering.approved
            ),
            operational_blocks=(
                analysis.filtering.operational_blocks if analysis else ()
            ),
            queue_status=queue_item.status if queue_item else "",
            scheduler_status=scheduler_status,
            reason=reason,
        )

    @staticmethod
    def calculate_metrics(run_id, results, decision, stage_totals, now):
        analyses = [item.analysis for item in results if item.analysis]
        scores = [item.score.total for item in analyses]
        valid = [
            item for item in analyses
            if OfferScore.number(item.candidate.current_price) > 0
        ]
        return OfferPipelineMetrics(
            run_id=run_id,
            received_count=len(results),
            valid_count=len(valid),
            discarded_count=sum(
                bool(item.queue_item and item.queue_item.status == "discarded")
                for item in results
            ),
            duplicate_count=sum(
                bool(item.analysis and item.analysis.duplicate
                     and item.analysis.duplicate.is_duplicate)
                for item in results
            ),
            blocked_count=sum(
                bool(item.queue_item and item.queue_item.status == "blocked")
                for item in results
            ),
            approved_count=sum(
                bool(item.analysis and item.analysis.filtering.approved)
                for item in results
            ),
            queued_count=sum(bool(item.queue_item) for item in results),
            selected_shadow_count=(
                decision.selected_count if decision else 0
            ),
            average_score=round(
                sum(scores) / len(scores) if scores else 0,
                3,
            ),
            average_processing_ms=round(
                sum(item.processing_ms for item in results) / len(results)
                if results else 0,
                3,
            ),
            stage_timings_ms=dict(stage_totals),
            created_at=now,
        )

    @staticmethod
    def scheduler_policy_from_environment():
        number = OfferIntelligenceService.env_number
        return OfferSchedulerPolicy(
            max_per_hour=int(number("OFFER_MAX_PER_HOUR", 3)),
            max_per_day=int(number("OFFER_MAX_PER_DAY", 12)),
            minimum_interval_minutes=int(number(
                "OFFER_MIN_INTERVAL_MINUTES", 15
            )),
            minimum_score=number("OFFER_MIN_SCORE", 70),
            excellent_score=number("OFFER_EXCELLENT_SCORE", 90),
            reservation_minutes=int(number(
                "OFFER_RESERVATION_MINUTES", 10
            )),
            default_expiration_hours=int(number(
                "OFFER_DEFAULT_EXPIRATION_HOURS", 12
            )),
            send_medium_offers=os.getenv(
                "SEND_MEDIUM_OFFERS", "False"
            ).strip().casefold() in {"1", "true", "yes", "on"},
            ranking_max_per_category=int(number(
                "RANKING_MAX_PER_CATEGORY", 1
            )),
            ranking_max_per_store=int(number(
                "RANKING_MAX_PER_STORE", 2
            )),
            ranking_max_per_identity=int(number(
                "RANKING_MAX_PER_IDENTITY", 1
            )),
        )

    @staticmethod
    def elapsed_ms(started):
        return (time.perf_counter() - started) * 1000

    @staticmethod
    def normalize_datetime(value):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
