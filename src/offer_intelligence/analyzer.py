from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from src.price_history.money import money, percent_change

from .confidence import ConfidenceAnalyzer
from .models import OfferIntelligence
from .rarity import RarityAnalyzer
from .statistics import basic_statistics, movement_frequencies
from .trend import TrendAnalyzer
from .volatility import VolatilityAnalyzer


class OfferIntelligenceAnalyzer:
    """Analisa observações válidas sem alterar histórico ou decisões."""

    def __init__(self, repository=None):
        self.repository = repository
        self.trends = TrendAnalyzer()
        self.volatility = VolatilityAnalyzer()
        self.confidence = ConfidenceAnalyzer()
        self.rarity = RarityAnalyzer()
        self.business_timezone = ZoneInfo("America/Sao_Paulo")

    def analyze(self, product_key, rows=None, now=None):
        if rows is None:
            if self.repository is None:
                rows = ()
            else:
                rows = self.repository.real_price_history(product_key)
        valid = [
            row for row in rows
            if int(self._value(row, "valid", 1) or 0) == 1
            and money(self._value(row, "price")) is not None
        ]
        valid.sort(key=lambda row: (
            self._datetime(self._value(row, "observed_at")), 
            int(self._value(row, "id", 0) or 0),
        ))
        generated_at = self._aware(now or datetime.now(timezone.utc))
        if not valid:
            return OfferIntelligence(
                product_key=product_key,
                generated_at=generated_at,
            )
        prices = [money(self._value(row, "price")) for row in valid]
        timestamps = [
            self._aware(self._datetime(self._value(row, "observed_at")))
            for row in valid
        ]
        statistics = basic_statistics(prices)
        volatility = self.volatility.calculate(
            statistics["average"], statistics["standard_deviation"],
            len(prices),
        )
        trend = self.trends.calculate(prices)
        reductions, increases = movement_frequencies(prices)
        local_timestamps = [
            timestamp.astimezone(self.business_timezone)
            for timestamp in timestamps
        ]
        days = {timestamp.date() for timestamp in local_timestamps}
        span_days = (
            local_timestamps[-1].date() - local_timestamps[0].date()
        ).days
        confidence = self.confidence.calculate(
            len(prices), len(days), span_days, volatility.stability_percent
        )
        rarity = self.rarity.calculate(prices[-1], prices)
        last_drop_at = next((
            timestamps[index]
            for index in range(len(prices) - 1, 0, -1)
            if prices[index] < prices[index - 1]
        ), None)
        minimum_at = max(
            timestamp for price, timestamp in zip(prices, timestamps)
            if price == statistics["minimum"]
        )
        maturity = self._maturity(len(prices), len(days), span_days)
        states = [maturity]
        if maturity not in {"UNKNOWN", "INSUFFICIENT_HISTORY"}:
            states.append(confidence.state)
        if rarity.state != "UNKNOWN":
            states.append(rarity.state)
        if (
            maturity not in {"UNKNOWN", "INSUFFICIENT_HISTORY"}
            and volatility.stability_percent is not None
            and volatility.stability_percent >= 95
        ):
            states.append("STABLE")
        states = tuple(dict.fromkeys(states))
        return OfferIntelligence(
            product_key=product_key,
            store=str(self._value(valid[-1], "store", "") or ""),
            title=str(self._value(valid[-1], "title", "") or ""),
            observation_count=len(prices),
            distinct_days=len(days),
            first_observed_at=timestamps[0],
            last_observed_at=timestamps[-1],
            current_price=prices[-1],
            minimum_price=statistics["minimum"],
            maximum_price=statistics["maximum"],
            average_price=statistics["average"],
            median_price=statistics["median"],
            volatility_percent=volatility.coefficient_percent,
            trend=trend.direction,
            trend_change_percent=trend.change_percent,
            reduction_frequency_percent=reductions,
            increase_frequency_percent=increases,
            time_since_last_drop_seconds=self._elapsed(
                generated_at, last_drop_at
            ),
            time_since_minimum_seconds=self._elapsed(
                generated_at, minimum_at
            ),
            distance_to_minimum_percent=percent_change(
                prices[-1], statistics["minimum"]
            ),
            distance_to_average_percent=percent_change(
                prices[-1], statistics["average"]
            ),
            stability_percent=volatility.stability_percent,
            confidence_index=confidence.index,
            rarity_index=rarity.index,
            rarity_percentile=rarity.percentile,
            state=states[0],
            states=states,
            generated_at=generated_at,
        )

    @staticmethod
    def _maturity(observations, distinct_days, span_days):
        if not observations:
            return "UNKNOWN"
        if observations < 2:
            return "INSUFFICIENT_HISTORY"
        if observations < 5 or distinct_days < 3 or span_days < 2:
            return "BUILDING_HISTORY"
        return "STABLE"

    @staticmethod
    def _value(row, key, default=None):
        try:
            return row[key]
        except (KeyError, IndexError, TypeError):
            return getattr(row, key, default)

    @staticmethod
    def _datetime(value):
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))

    @staticmethod
    def _aware(value):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _elapsed(now, event):
        if event is None:
            return None
        return max(int((now - event).total_seconds()), 0)
