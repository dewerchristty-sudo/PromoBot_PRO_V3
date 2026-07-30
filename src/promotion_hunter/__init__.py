"""Fundação isolada do Caçador Automático de Promoções."""

from .contracts import CollectionResult, PromotionCollector, PromotionSource
from .decision_mapper import DecisionMapper
from .models import (
    DecisionStatus,
    HunterDecision,
    HunterRunResult,
    NormalizedProduct,
)
from .normalization import ProductNormalizer
from .registry import CollectorRegistry, UnsupportedPromotionSource
from .repository import PromotionHunterRepository
from .service import PromotionHunterService

__all__ = [
    "CollectionResult",
    "CollectorRegistry",
    "DecisionMapper",
    "DecisionStatus",
    "HunterDecision",
    "HunterRunResult",
    "NormalizedProduct",
    "ProductNormalizer",
    "PromotionCollector",
    "PromotionHunterRepository",
    "PromotionHunterService",
    "PromotionSource",
    "UnsupportedPromotionSource",
]
