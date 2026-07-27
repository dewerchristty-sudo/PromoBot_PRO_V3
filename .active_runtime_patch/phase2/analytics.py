from collections import Counter
from dataclasses import dataclass
from typing import Dict, Iterable

from .models import ApprovalDecision, OfferSnapshot


@dataclass(frozen=True)
class DashboardSnapshot:
    products: int
    approved: int
    rejected: int
    average_discount: float
    largest_discount: float
    by_store: Dict[str, int]
    by_category: Dict[str, int]
    by_group: Dict[str, int]


class DashboardStatistics:
    """Agregador puro; não consulta nem modifica o banco atual."""

    @staticmethod
    def build(
        offers: Iterable[OfferSnapshot],
        decisions: Dict[str, ApprovalDecision],
    ) -> DashboardSnapshot:
        items = list(offers)
        discounts = [
            ((item.previous_price - item.current_price) / item.previous_price) * 100
            for item in items
            if item.previous_price and item.previous_price > item.current_price
        ]
        return DashboardSnapshot(
            products=len(items),
            approved=sum(value == ApprovalDecision.APPROVED for value in decisions.values()),
            rejected=sum(value == ApprovalDecision.REJECTED for value in decisions.values()),
            average_discount=sum(discounts) / len(discounts) if discounts else 0.0,
            largest_discount=max(discounts, default=0.0),
            by_store=dict(Counter(item.store for item in items)),
            by_category=dict(Counter(item.category for item in items if item.category)),
            by_group=dict(Counter(item.group for item in items if item.group)),
        )
