from dataclasses import dataclass, replace
from datetime import datetime, timezone
import logging
import os
from typing import Mapping, Any

from .filters import FilterResult, OfferFilter
from .duplicates import DuplicateChecker
from .history import OfferHistory
from .identity import OfferIdentity
from .models import (
    DuplicateCheckResult,
    OfferCandidate,
    OfferHistoryResult,
    OfferIdentityResult,
    RankedOffer,
    ScoreResult,
)
from .policy import OfferAnalysisPolicy
from .ranking import OfferRanking
from .score import OfferScore
from src.stores.active import is_active_store


@dataclass(frozen=True, slots=True)
class OfferAnalysis:
    candidate: OfferCandidate
    score: ScoreResult
    filtering: FilterResult
    feature_enabled: bool
    identity: OfferIdentityResult | None = None
    history: OfferHistoryResult | None = None
    duplicate: DuplicateCheckResult | None = None
    shadow_mode: bool = True
    affects_current_flow: bool = False


class OfferIntelligenceService:
    """Ponto opcional de análise; não possui integração com envio nesta fase."""

    def __init__(
        self,
        scorer: OfferScore | None = None,
        offer_filter: OfferFilter | None = None,
        identity: OfferIdentity | None = None,
        history: OfferHistory | None = None,
        duplicate_checker: DuplicateChecker | None = None,
        ranking: OfferRanking | None = None,
        analysis_policy: OfferAnalysisPolicy | None = None,
        logger: logging.Logger | None = None,
    ):
        self.analysis_policy = analysis_policy or self.policy_from_environment()
        self.scorer = scorer or OfferScore()
        self.offer_filter = offer_filter or OfferFilter()
        self.identity = identity or OfferIdentity()
        self.history = history or OfferHistory(policy=self.analysis_policy)
        self.duplicate_checker = duplicate_checker or DuplicateChecker(
            policy=self.analysis_policy
        )
        self.ranking = ranking or OfferRanking(self.analysis_policy)
        self.logger = logger or logging.getLogger("promobot.offer_score")

    def analyze(
        self,
        product: OfferCandidate | Mapping[str, Any],
        now: datetime | None = None,
    ) -> OfferAnalysis:
        candidate = (
            product
            if isinstance(product, OfferCandidate)
            else OfferCandidate.from_mapping(product)
        )
        if candidate.store.strip() and not is_active_store(candidate.store):
            raise ValueError(
                f"Loja inativa para o dominio atual: {candidate.store}"
            )
        identity_result = self.identity.identify(candidate)
        current_price = OfferScore.number(candidate.current_price)
        reference = now or candidate.collected_at or datetime.now(timezone.utc)
        if current_price > 0:
            self.history.record(
                identity_result.signature,
                current_price,
                reference,
                candidate.store,
                store=candidate.store,
                title=candidate.title,
                currency=str(
                    (candidate.future_signals or {}).get("currency", "BRL")
                ),
                original_url=candidate.product_link,
                image_url=candidate.image_url,
                availability=candidate.availability,
            )
        history_result = self.history.analyze(
            identity_result.signature,
            current_price,
            now=reference,
        )
        history_span_hours = 0.0
        if len(history_result.observations) >= 2:
            history_span_hours = (
                history_result.observations[-1].observed_at
                - history_result.observations[0].observed_at
            ).total_seconds() / 3600
        history_reliable_for_score = bool(
            history_result.reliable and history_span_hours >= 24
        )
        future_signals = dict(candidate.future_signals or {})
        future_signals.update({
            "history_span_hours": round(max(history_span_hours, 0.0), 3),
            "history_reliable_for_score": history_reliable_for_score,
            "history_sample_count": history_result.sample_count,
            "discount_verified": bool(
                candidate.previous_price_validated
                and OfferScore.number(candidate.previous_price) > current_price
            ),
            "history_observed_days": history_result.observed_days,
            "history_temporal_confidence": (
                history_result.temporal_confidence
            ),
            "history_trend": history_result.trend,
            "history_is_new_record": history_result.is_new_record,
            "history_drop_percent": history_result.drop_percent,
            "history_events": history_result.events,
        })
        enriched_candidate = replace(
            candidate,
            historical_reference_price=(
                history_result.maximum
                if history_result.sample_count
                else candidate.historical_reference_price
            ),
            historical_minimum=(
                history_result.minimum
                if history_result.sample_count
                else candidate.historical_minimum
            ),
            historical_percentile=history_result.percentile,
            price_sample_count=max(
                candidate.price_sample_count,
                history_result.sample_count,
            ),
            future_signals=future_signals,
        )
        score = self.scorer.calculate(enriched_candidate)
        filtering = self.offer_filter.analyze(enriched_candidate)
        duplicate = self.duplicate_checker.check(
            identity_result,
            current_price,
            now=reference,
        )
        analysis = OfferAnalysis(
            candidate=enriched_candidate,
            score=score,
            filtering=filtering,
            feature_enabled=self.feature_enabled(),
            identity=identity_result,
            history=history_result,
            duplicate=duplicate,
        )
        self.logger.info(
            "OfferScore sombra: product_id=%r store=%r score=%.2f "
            "classification=%s approved=%s operational_blocks=%s",
            candidate.product_id,
            candidate.store,
            score.total,
            score.classification,
            filtering.approved,
            filtering.operational_blocks,
        )
        return analysis

    def analyze_batch(
        self,
        products: list[OfferCandidate | Mapping[str, Any]],
        limit: int = 3,
    ) -> list[RankedOffer]:
        analyses = [self.analyze(product) for product in products]
        rankable = [
            RankedOffer(
                candidate=analysis.candidate,
                score=analysis.score,
                identity=analysis.identity,
                duplicate=analysis.duplicate,
                history=analysis.history,
            )
            for analysis in analyses
            if analysis.identity is not None
        ]
        return self.ranking.rank(rankable, limit=limit)

    def remember_for_duplicate_analysis(
        self,
        product: OfferCandidate | Mapping[str, Any],
        occurred_at: datetime | None = None,
    ):
        candidate = (
            product
            if isinstance(product, OfferCandidate)
            else OfferCandidate.from_mapping(product)
        )
        identity = self.identity.identify(candidate)
        return self.duplicate_checker.remember(
            identity,
            OfferScore.number(candidate.current_price),
            occurred_at,
        )

    def enqueue_shadow_analysis(self, product, queue):
        """Analisa e persiste opcionalmente, sem executar scheduler ou envio."""

        analysis = self.analyze(product)
        ranked = RankedOffer(
            candidate=analysis.candidate,
            score=analysis.score,
            identity=analysis.identity,
            duplicate=analysis.duplicate,
            history=analysis.history,
        )
        operational = list(analysis.filtering.operational_blocks)
        if analysis.duplicate and analysis.duplicate.is_duplicate:
            operational.append("duplicidade_ativa")
        return queue.enqueue_ranked(ranked, operational)

    @staticmethod
    def feature_enabled() -> bool:
        return os.getenv("OFFER_SCORE_ENABLED", "False").strip().casefold() in {
            "1",
            "true",
            "yes",
            "on",
        }

    @staticmethod
    def policy_from_environment() -> OfferAnalysisPolicy:
        return OfferAnalysisPolicy(
            duplicate_window_hours=OfferIntelligenceService.env_number(
                "DUPLICATE_WINDOW_HOURS",
                24,
            ),
            significant_price_drop_percent=OfferIntelligenceService.env_number(
                "SIGNIFICANT_PRICE_DROP_PERCENT",
                5,
            ),
            history_minimum_samples=int(
                OfferIntelligenceService.env_number(
                    "HISTORY_MINIMUM_SAMPLES",
                    3,
                )
            ),
            history_window_days=int(
                OfferIntelligenceService.env_number(
                    "HISTORY_WINDOW_DAYS",
                    90,
                )
            ),
            ranking_max_per_category=int(
                OfferIntelligenceService.env_number(
                    "RANKING_MAX_PER_CATEGORY",
                    1,
                )
            ),
            ranking_max_per_store=int(
                OfferIntelligenceService.env_number(
                    "RANKING_MAX_PER_STORE",
                    2,
                )
            ),
        )

    @staticmethod
    def env_number(name: str, default: float) -> float:
        try:
            return float(os.getenv(name, str(default)) or default)
        except ValueError:
            return float(default)