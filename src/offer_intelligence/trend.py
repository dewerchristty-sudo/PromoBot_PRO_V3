from decimal import Decimal

from src.price_history.money import percent_change

from .models import TrendResult
from .statistics import rounded


class TrendAnalyzer:

    def calculate(self, prices):
        count = len(prices)
        if count < 2:
            return TrendResult()
        x_average = Decimal(count - 1) / Decimal("2")
        y_average = sum(prices) / Decimal(count)
        numerator = sum(
            (Decimal(index) - x_average) * (price - y_average)
            for index, price in enumerate(prices)
        )
        denominator = sum(
            (Decimal(index) - x_average) ** 2
            for index in range(count)
        )
        slope = numerator / denominator if denominator else Decimal("0")
        change = percent_change(prices[-1], prices[0])
        relative_slope = (
            abs(slope) / y_average * 100 if y_average > 0 else Decimal("0")
        )
        if relative_slope < Decimal("0.5"):
            direction = "STABLE"
        elif slope < 0:
            direction = "FALLING"
        else:
            direction = "RISING"
        return TrendResult(direction, rounded(slope), change)
