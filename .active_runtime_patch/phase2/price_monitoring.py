from typing import Iterable, Optional

from .models import PriceAnalysis, PriceMovement, PriceObservation


class PriceTrendAnalyzer:
    """Compara observações sem coletar preços e sem disparar notificações."""

    def analyze(
        self,
        current: PriceObservation,
        history: Iterable[PriceObservation],
    ) -> PriceAnalysis:
        prior: Optional[PriceObservation] = None
        for item in history:
            if item.product_key != current.product_key:
                continue
            if item.observed_at >= current.observed_at:
                continue
            if prior is None or item.observed_at > prior.observed_at:
                prior = item

        if prior is None:
            return PriceAnalysis(
                current.product_key,
                PriceMovement.UNKNOWN,
                current.price,
                None,
            )

        change = current.price - prior.price
        movement = PriceMovement.UNCHANGED
        if change < 0:
            movement = PriceMovement.DECREASED
        elif change > 0:
            movement = PriceMovement.INCREASED
        percentage = (change / prior.price * 100) if prior.price else 0.0
        return PriceAnalysis(
            current.product_key,
            movement,
            current.price,
            prior.price,
            change,
            percentage,
        )
