from dataclasses import replace
from datetime import datetime, timezone
from typing import Iterable

from .models import RankedOffer
from .policy import OfferAnalysisPolicy
from .score import OfferScore
from src.stores.active import is_active_store


class OfferRanking:
    """Ranking determinístico com deduplicação e diversidade opcional."""

    CLASSIFICATION_PRIORITY = {
        "oferta_excepcional": 5,
        "oferta_muito_boa": 4,
        "oferta_boa": 3,
        "oferta_regular": 2,
        "oferta_fraca_sem_evidencia": 1,
        "oferta_excelente": 4,
        "boa_oferta": 3,
        "oferta_media": 2,
        "oferta_fraca": 1,
    }

    def __init__(self, policy: OfferAnalysisPolicy | None = None):
        self.policy = policy or OfferAnalysisPolicy()

    def rank(
        self,
        offers: Iterable[RankedOffer],
        limit: int = 3,
        diversity: bool = True,
    ) -> list[RankedOffer]:
        limit = max(int(limit), 0)
        if limit == 0:
            return []

        unique: dict[str, RankedOffer] = {}
        for offer in offers:
            if not is_active_store(offer.candidate.store):
                continue
            key = offer.identity.signature
            current = unique.get(key)
            if current is None or self.sort_key(offer) < self.sort_key(current):
                unique[key] = offer

        ordered = sorted(unique.values(), key=self.sort_key)
        if not diversity:
            selected = ordered[:limit]
        else:
            selected, skipped = self.apply_diversity(ordered, limit)
            if (
                len(selected) < limit
                and self.policy.ranking_allow_repetition_if_needed
            ):
                selected.extend(skipped[:limit - len(selected)])

        return [
            replace(offer, rank=index)
            for index, offer in enumerate(selected[:limit], start=1)
        ]

    def apply_diversity(
        self,
        ordered: list[RankedOffer],
        limit: int,
    ) -> tuple[list[RankedOffer], list[RankedOffer]]:
        selected: list[RankedOffer] = []
        skipped: list[RankedOffer] = []
        categories: dict[str, int] = {}
        stores: dict[str, int] = {}
        identities: dict[str, int] = {}

        for offer in ordered:
            category = offer.candidate.category.strip().casefold() or "sem_categoria"
            store = offer.candidate.store.strip().casefold() or "sem_loja"
            identity = offer.identity.signature
            exceeds = (
                categories.get(category, 0)
                >= self.policy.ranking_max_per_category
                or stores.get(store, 0) >= self.policy.ranking_max_per_store
                or identities.get(identity, 0)
                >= self.policy.ranking_max_per_identity
            )
            if exceeds:
                skipped.append(offer)
                continue
            selected.append(offer)
            categories[category] = categories.get(category, 0) + 1
            stores[store] = stores.get(store, 0) + 1
            identities[identity] = identities.get(identity, 0) + 1
            if len(selected) >= limit:
                break
        return selected, skipped

    def sort_key(self, offer: RankedOffer) -> tuple:
        current = OfferScore.number(offer.candidate.current_price)
        previous = OfferScore.number(
            offer.candidate.historical_reference_price
            or offer.candidate.previous_price
        )
        saving = max(previous - current, 0.0)
        minimum = (
            offer.history.minimum
            if offer.history is not None
            else OfferScore.number(offer.candidate.historical_minimum)
        )
        distance = (
            ((current - minimum) / minimum) * 100
            if current > 0 and minimum > 0
            else float("inf")
        )
        collected = offer.candidate.collected_at
        if not isinstance(collected, datetime):
            timestamp = 0.0
        else:
            if collected.tzinfo is None:
                collected = collected.replace(tzinfo=timezone.utc)
            timestamp = collected.timestamp()
        duplicate_penalty = int(bool(
            offer.duplicate and offer.duplicate.is_duplicate
        ))
        return (
            duplicate_penalty,
            -offer.score.total,
            -self.CLASSIFICATION_PRIORITY.get(
                offer.score.classification,
                0,
            ),
            -offer.score.confidence,
            -saving,
            distance,
            -timestamp,
            offer.identity.signature,
        )

    def top3(self, offers: Iterable[RankedOffer]) -> list[RankedOffer]:
        return self.rank(offers, 3)

    def top5(self, offers: Iterable[RankedOffer]) -> list[RankedOffer]:
        return self.rank(offers, 5)

    def top10(self, offers: Iterable[RankedOffer]) -> list[RankedOffer]:
        return self.rank(offers, 10)
