from decimal import Decimal

from .models import ConfidenceResult
from .statistics import rounded


class ConfidenceAnalyzer:
    """Confiança estatística da amostra; não é sinal para o Offer Score."""

    def calculate(self, observations, distinct_days, span_days, stability):
        if not observations:
            return ConfidenceResult()
        observation_component = min(Decimal(observations) / 10, Decimal("1"))
        day_component = min(Decimal(distinct_days) / 7, Decimal("1"))
        span_component = min(Decimal(span_days) / 14, Decimal("1"))
        stability_component = (stability or Decimal("0")) / 100
        index = rounded((
            observation_component * Decimal("0.35")
            + day_component * Decimal("0.30")
            + span_component * Decimal("0.20")
            + stability_component * Decimal("0.15")
        ) * 100)
        return ConfidenceResult(
            index=index,
            state="HIGH_CONFIDENCE" if index >= 70 else "LOW_CONFIDENCE",
        )
