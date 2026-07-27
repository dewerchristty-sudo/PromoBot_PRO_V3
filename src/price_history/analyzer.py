from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from statistics import median
from zoneinfo import ZoneInfo

from .money import money, percent_change
from .models import PriceHistoryAnalysis


class PriceHistoryAnalyzer:

    BUSINESS_TIMEZONE = ZoneInfo("America/Sao_Paulo")

    def __init__(self, config):
        self.config = config

    def analyze(self, product_key, rows, rejections=()):
        valid = [row for row in rows if int(row["valid"] or 0) == 1]
        prices = [money(row["price"]) for row in valid]
        prices = [price for price in prices if price is not None]
        days = {
            self.local_datetime(row["observed_at"]).date()
            for row in valid
        }
        count = len(prices)
        first = prices[0] if prices else None
        last = prices[-1] if prices else None
        minimum = min(prices) if prices else None
        maximum = max(prices) if prices else None
        average = (
            (sum(prices) / Decimal(count)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            ) if prices else None
        )
        med = money(median(prices)) if prices else None
        previous_change = (
            percent_change(last, prices[-2]) if count >= 2 else None
        )
        span_days = 0
        if len(valid) >= 2:
            first_date = self.local_datetime(valid[0]["observed_at"])
            last_date = self.local_datetime(valid[-1]["observed_at"])
            span_days = (last_date.date() - first_date.date()).days
        outliers = sum(
            row["reason"] == "OUTLIER_PERCENT" for row in rejections
        )
        if not count:
            maturity = "NO_HISTORY"
        elif outliers:
            maturity = "ANOMALOUS_HISTORY"
        elif (
            count >= self.config.min_observations
            and len(days) >= self.config.min_distinct_days
        ):
            maturity = (
                "STABLE_HISTORY"
                if span_days >= self.config.stable_days
                and maximum is not None and minimum is not None
                and percent_change(maximum, minimum)
                <= Decimal(str(self.config.outlier_percent))
                else "SUFFICIENT_HISTORY"
            )
        elif count >= 2 and len(days) >= 2:
            maturity = "BUILDING_HISTORY"
        else:
            maturity = "INSUFFICIENT_HISTORY"
        confidence = min(
            Decimal(count) / Decimal(self.config.min_observations),
            Decimal(len(days)) / Decimal(self.config.min_distinct_days),
            Decimal("1"),
        ) * Decimal("100") if count else Decimal("0")
        drop_amount = (
            prices[-2] - last if count >= 2 else Decimal("0")
        )
        drop_percent = (
            -previous_change
            if previous_change is not None and previous_change < 0
            else Decimal("0")
        )
        real_drop = bool(
            drop_amount >= Decimal(self.config.change_min_amount)
            and drop_percent >= Decimal(self.config.change_min_percent)
        )
        sufficient = maturity in {
            "SUFFICIENT_HISTORY", "STABLE_HISTORY"
        }
        next_requirement = self.next_requirement(count, len(days))
        return PriceHistoryAnalysis(
            product_key=product_key,
            store=valid[-1]["store"] if valid else "",
            title=valid[-1]["title"] if valid else "",
            valid_observations=count,
            ignored_observations=len(rejections),
            distinct_days=len(days),
            first_price=first, last_price=last,
            minimum=minimum, maximum=maximum,
            average=average, median=med,
            variation_from_previous_percent=previous_change,
            variation_from_average_percent=percent_change(last, average),
            variation_from_minimum_percent=percent_change(last, minimum),
            maturity=maturity,
            confidence=confidence.quantize(Decimal("0.01")),
            real_drop_confirmed=real_drop,
            next_requirement=next_requirement,
            score_signals={
                "history_reliable_for_score": sufficient,
                "history_sample_count": count,
                "history_observed_days": len(days),
                "historical_minimum": str(minimum) if sufficient else "",
                "historical_reference_price":
                    str(average) if sufficient else "",
                "discount_verified": bool(sufficient and real_drop),
            },
        )

    def next_requirement(self, count, days):
        missing_observations = max(
            self.config.min_observations - count, 0
        )
        missing_days = max(self.config.min_distinct_days - days, 0)
        if not missing_observations and not missing_days:
            return "Requisitos minimos atingidos."
        return (
            f"Faltam {missing_observations} observacoes validas e "
            f"{missing_days} dias distintos."
        )

    @classmethod
    def local_datetime(cls, value):
        parsed = (
            value if isinstance(value, datetime)
            else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        )
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=cls.BUSINESS_TIMEZONE)
        return parsed.astimezone(cls.BUSINESS_TIMEZONE)
