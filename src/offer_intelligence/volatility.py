from decimal import Decimal

from .models import VolatilityResult
from .statistics import rounded


class VolatilityAnalyzer:

    def calculate(self, average, standard_deviation, sample_count):
        if sample_count < 2 or average is None or average <= 0:
            return VolatilityResult()
        coefficient = rounded(standard_deviation / average * 100)
        stability = rounded(max(Decimal("0"), Decimal("100") - coefficient))
        return VolatilityResult(
            standard_deviation=standard_deviation,
            coefficient_percent=coefficient,
            stability_percent=stability,
        )
