from decimal import Decimal

from .models import RarityResult
from .statistics import rounded


class RarityAnalyzer:
    """Mede quão incomum é um preço baixo dentro da amostra observada."""

    def calculate(self, current, prices):
        if current is None or len(prices) < 3:
            return RarityResult()
        at_or_below = sum(price <= current for price in prices)
        percentile = rounded(Decimal(at_or_below) / Decimal(len(prices)) * 100)
        rarity = rounded(Decimal("100") - percentile)
        state = "RARE_PRICE" if percentile <= 20 else "COMMON_PRICE"
        return RarityResult(rarity, percentile, state)
