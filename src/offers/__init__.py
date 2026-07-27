"""Domínio isolado de análise inteligente de ofertas."""

from .detector import OfferDetection, OfferDetector, OfferDetectorConfig, OfferRating
from .filters import FilterResult, OfferFilter, OfferFilterPolicy
from .duplicates import (
    DuplicateChecker,
    InMemoryDuplicateHistoryStore,
    PreviousOffer,
)
from .history import (
    InMemoryOfferHistoryStore,
    OfferHistory,
    OfferHistoryStore,
)
from .identity import OfferIdentity
from .models import (
    DuplicateCheckResult,
    OfferCandidate,
    OfferHistoryResult,
    OfferIdentityResult,
    PriceObservation,
    RankedOffer,
    QueueOffer,
    SchedulerDecision,
    ScoreResult,
    SkippedOffer,
)
from .policy import (
    OfferAnalysisPolicy,
    OfferSchedulerPolicy,
    OfferScorePolicy,
)
from .ranking import OfferRanking
from .score import OfferScore
from .service import OfferAnalysis, OfferIntelligenceService
from .price_history_dashboard import PriceHistoryDashboard

__all__ = [
    "FilterResult",
    "OfferDetection",
    "OfferDetector",
    "OfferDetectorConfig",
    "OfferRating",
    "DuplicateChecker",
    "DuplicateCheckResult",
    "InMemoryDuplicateHistoryStore",
    "InMemoryOfferHistoryStore",
    "OfferAnalysis",
    "OfferAnalysisPolicy",
    "OfferCandidate",
    "OfferFilter",
    "OfferFilterPolicy",
    "OfferHistory",
    "OfferHistoryResult",
    "OfferHistoryStore",
    "OfferIdentity",
    "OfferIdentityResult",
    "OfferIntelligenceService",
    "OfferRanking",
    "OfferSchedulerPolicy",
    "OfferScore",
    "OfferScorePolicy",
    "PreviousOffer",
    "PriceObservation",
    "PriceHistoryDashboard",
    "QueueOffer",
    "RankedOffer",
    "SchedulerDecision",
    "ScoreResult",
    "SkippedOffer",
]
