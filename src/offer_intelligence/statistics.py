from decimal import Decimal, ROUND_HALF_UP
from statistics import median, pstdev


HUNDREDTH = Decimal("0.01")


def rounded(value):
    if value is None:
        return None
    return Decimal(str(value)).quantize(HUNDREDTH, rounding=ROUND_HALF_UP)


def basic_statistics(prices):
    if not prices:
        return {
            "minimum": None, "maximum": None, "average": None,
            "median": None, "standard_deviation": None,
        }
    count = Decimal(len(prices))
    average = sum(prices) / count
    deviation = Decimal("0") if len(prices) == 1 else Decimal(pstdev(prices))
    return {
        "minimum": min(prices),
        "maximum": max(prices),
        "average": rounded(average),
        "median": rounded(median(prices)),
        "standard_deviation": rounded(deviation),
    }


def movement_frequencies(prices):
    comparisons = len(prices) - 1
    if comparisons <= 0:
        return None, None
    reductions = sum(current < previous for previous, current in zip(
        prices, prices[1:]
    ))
    increases = sum(current > previous for previous, current in zip(
        prices, prices[1:]
    ))
    denominator = Decimal(comparisons)
    return (
        rounded(Decimal(reductions) / denominator * 100),
        rounded(Decimal(increases) / denominator * 100),
    )
