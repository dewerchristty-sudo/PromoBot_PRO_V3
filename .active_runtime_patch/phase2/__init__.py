"""Fundação opt-in da Fase 2.

Este pacote não é importado pelo runtime atual. Seus componentes são puros e
somente passam a produzir efeitos quando receberem adaptadores explicitamente.
"""

from .facade import Phase2Foundation
from .models import (
    ApprovalDecision,
    OfferSnapshot,
    PriceMovement,
    PublicationPlan,
)

__all__ = [
    "ApprovalDecision",
    "OfferSnapshot",
    "Phase2Foundation",
    "PriceMovement",
    "PublicationPlan",
]
