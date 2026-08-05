from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .models import DuplicateCheckResult, OfferIdentityResult
from .policy import OfferAnalysisPolicy
from .score import OfferScore


@dataclass(frozen=True, slots=True)
class PreviousOffer:
    identity_signature: str
    similarity_signature: str
    link_signature: str
    promotion_signature: str
    price: float
    occurred_at: datetime


class DuplicateHistoryStore(ABC):

    @abstractmethod
    def add(self, offer: PreviousOffer) -> None:
        raise NotImplementedError

    @abstractmethod
    def recent(self, since: datetime) -> list[PreviousOffer]:
        raise NotImplementedError


class InMemoryDuplicateHistoryStore(DuplicateHistoryStore):

    def __init__(self):
        self._items: list[PreviousOffer] = []

    def add(self, offer: PreviousOffer) -> None:
        self._items.append(offer)

    def recent(self, since: datetime) -> list[PreviousOffer]:
        since = DuplicateChecker.normalize_datetime(since)
        return [
            item for item in self._items
            if DuplicateChecker.normalize_datetime(item.occurred_at) >= since
        ]


class PersistentDuplicateHistoryStore(DuplicateHistoryStore):
    """Adapta o repositório do pipeline ao contrato de deduplicação.

    O repositório é responsável pela transação e pelo armazenamento. Assim o
    checker continua independente de SQLite e pode ser testado em memória.
    """

    def __init__(self, repository):
        self.repository = repository

    def add(self, offer: PreviousOffer) -> None:
        self.repository.add_duplicate_offer(offer)

    def recent(self, since: datetime) -> list[PreviousOffer]:
        return self.repository.recent_duplicate_offers(since)


class DuplicateChecker:

    def __init__(
        self,
        store: DuplicateHistoryStore | None = None,
        policy: OfferAnalysisPolicy | None = None,
    ):
        self.store = store or InMemoryDuplicateHistoryStore()
        self.policy = policy or OfferAnalysisPolicy()

    def remember(
        self,
        identity: OfferIdentityResult,
        price: float,
        occurred_at: datetime | None = None,
    ) -> PreviousOffer:
        item = PreviousOffer(
            identity_signature=identity.signature,
            similarity_signature=identity.similarity_signature,
            link_signature=identity.link_signature,
            promotion_signature=identity.promotion_signature,
            price=OfferScore.number(price),
            occurred_at=self.normalize_datetime(
                occurred_at or datetime.now(timezone.utc)
            ),
        )
        self.store.add(item)
        return item

    def check(
        self,
        identity: OfferIdentityResult,
        current_price: float,
        now: datetime | None = None,
    ) -> DuplicateCheckResult:
        now = self.normalize_datetime(now or datetime.now(timezone.utc))
        window = timedelta(hours=self.policy.duplicate_window_hours)
        recent = sorted(
            self.store.recent(now - window),
            key=lambda item: item.occurred_at,
            reverse=True,
        )
        current = OfferScore.number(current_price)

        for previous in recent:
            duplicate_type = self.match_type(identity, previous)
            if not duplicate_type:
                continue
            drop = self.price_drop_percent(previous.price, current)
            if drop >= self.policy.significant_price_drop_percent:
                return DuplicateCheckResult(
                    is_duplicate=False,
                    duplicate_type="nova_promocao",
                    previous_match=previous,
                    blocked_until=None,
                    reasons=(
                        f"Queda relevante de {drop:.2f}% permite nova promoção.",
                    ),
                )
            blocked_until = self.normalize_datetime(
                previous.occurred_at
            ) + window
            return DuplicateCheckResult(
                is_duplicate=True,
                duplicate_type=duplicate_type,
                previous_match=previous,
                blocked_until=blocked_until,
                reasons=(
                    f"Correspondência por {duplicate_type}.",
                    f"Queda de {drop:.2f}% abaixo do limite configurado.",
                ),
            )

        return DuplicateCheckResult(
            is_duplicate=False,
            duplicate_type="novo_produto",
            previous_match=None,
            blocked_until=None,
            reasons=("Nenhuma ocorrência correspondente dentro da janela.",),
        )

    @staticmethod
    def match_type(
        identity: OfferIdentityResult,
        previous: PreviousOffer,
    ) -> str:
        if (
            identity.link_signature
            and identity.link_signature == previous.link_signature
        ):
            return "mesmo_link"
        if identity.promotion_signature == previous.promotion_signature:
            return "mesma_promocao"
        if identity.signature == previous.identity_signature:
            return "mesmo_produto"
        if identity.similarity_signature == previous.similarity_signature:
            return "produto_semelhante"
        return ""

    @staticmethod
    def price_drop_percent(previous_price: float, current_price: float) -> float:
        previous = OfferScore.number(previous_price)
        current = OfferScore.number(current_price)
        if previous <= 0 or current <= 0 or current >= previous:
            return 0.0
        return ((previous - current) / previous) * 100

    @staticmethod
    def normalize_datetime(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
