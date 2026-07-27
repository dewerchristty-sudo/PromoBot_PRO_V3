from typing import Iterable, Optional, Protocol

from .models import OfferSnapshot, PriceObservation, PublicationPlan


class OfferSource(Protocol):
    """Contrato futuro para fontes de ofertas, sem acoplamento às lojas atuais."""

    def collect(self, query: str) -> Iterable[OfferSnapshot]:
        ...


class PublicationPlanRepository(Protocol):
    def add(self, plan: PublicationPlan) -> None:
        ...

    def get(self, plan_id: str) -> Optional[PublicationPlan]:
        ...

    def pending(self) -> Iterable[PublicationPlan]:
        ...


class PriceObservationRepository(Protocol):
    def append(self, observation: PriceObservation) -> None:
        ...

    def for_product(self, product_key: str) -> Iterable[PriceObservation]:
        ...


class OfferPublisher(Protocol):
    """Porta futura. Nenhuma implementação é fornecida nesta etapa."""

    def publish(self, plan: PublicationPlan) -> bool:
        ...
