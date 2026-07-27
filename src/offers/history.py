from abc import ABC, abstractmethod
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import math
import statistics

from .models import OfferHistoryResult, PriceObservation
from .policy import OfferAnalysisPolicy
from .score import OfferScore


class OfferHistoryStore(ABC):

    @abstractmethod
    def add(self, observation: PriceObservation) -> bool:
        raise NotImplementedError

    @abstractmethod
    def list_for(
        self,
        identity: str,
        since: datetime | None = None,
    ) -> list[PriceObservation]:
        raise NotImplementedError


class InMemoryOfferHistoryStore(OfferHistoryStore):

    def __init__(self):
        self._observations: dict[str, list[PriceObservation]] = defaultdict(list)

    def add(self, observation: PriceObservation) -> bool:
        price = OfferScore.number(observation.price)
        if price <= 0 or not observation.identity:
            return False
        observed_at = OfferHistory.normalize_datetime(observation.observed_at)
        items = self._observations[observation.identity]
        if any(
            item.observed_at.date() == observed_at.date()
            and OfferScore.number(item.price) == price
            for item in items
        ):
            return False
        normalized = PriceObservation(
            identity=observation.identity,
            price=price,
            observed_at=observed_at,
            source=observation.source,
            store=observation.store,
            title=observation.title,
            currency=observation.currency or "BRL",
            original_url=observation.original_url,
            image_url=observation.image_url,
            availability=observation.availability,
        )
        items.append(normalized)
        items.sort(key=lambda item: item.observed_at)
        return True

    def list_for(
        self,
        identity: str,
        since: datetime | None = None,
    ) -> list[PriceObservation]:
        items = list(self._observations.get(identity, ()))
        if since is None:
            return items
        since = OfferHistory.normalize_datetime(since)
        return [item for item in items if item.observed_at >= since]


class OfferHistory:

    def __init__(
        self,
        store: OfferHistoryStore | None = None,
        policy: OfferAnalysisPolicy | None = None,
    ):
        self.store = store or InMemoryOfferHistoryStore()
        self.policy = policy or OfferAnalysisPolicy()

    def record(
        self,
        identity: str,
        price: float,
        observed_at: datetime | None = None,
        source: str = "",
        *,
        store: str = "",
        title: str = "",
        currency: str = "BRL",
        original_url: str = "",
        image_url: str = "",
        availability: str = "",
    ) -> bool:
        return self.store.add(PriceObservation(
            identity=identity,
            price=price,
            observed_at=self.normalize_datetime(
                observed_at or datetime.now(timezone.utc)
            ),
            source=source,
            store=store,
            title=title,
            currency=currency or "BRL",
            original_url=original_url,
            image_url=image_url,
            availability=availability,
        ))

    def full_history(self, identity: str) -> list[PriceObservation]:
        return self.store.list_for(identity)

    def last_days(
        self,
        identity: str,
        days: int,
        now: datetime | None = None,
    ) -> list[PriceObservation]:
        now = self.normalize_datetime(now or datetime.now(timezone.utc))
        return self.store.list_for(
            identity, now - timedelta(days=max(int(days), 1))
        )

    def last_7_days(self, identity, now=None):
        return self.last_days(identity, 7, now)

    def last_30_days(self, identity, now=None):
        return self.last_days(identity, 30, now)

    def analyze(
        self,
        identity: str,
        current_price: float | None = None,
        now: datetime | None = None,
        window_days: int | None = None,
    ) -> OfferHistoryResult:
        now = self.normalize_datetime(now or datetime.now(timezone.utc))
        days = (
            self.policy.history_window_days
            if window_days is None else max(int(window_days), 1)
        )
        observations = self.store.list_for(
            identity, now - timedelta(days=days)
        )
        observations = tuple(sorted(
            (
                item for item in observations
                if OfferScore.number(item.price) > 0
            ),
            key=lambda item: item.observed_at,
        ))
        prices = [OfferScore.number(item.price) for item in observations]
        count = len(prices)
        observed_days = len({item.observed_at.date() for item in observations})
        reliable = observed_days >= self.policy.history_minimum_samples
        current = OfferScore.number(current_price)
        if current <= 0 and prices:
            current = prices[-1]
        minimum = min(prices) if prices else 0.0
        maximum = max(prices) if prices else 0.0
        average = statistics.fmean(prices) if prices else 0.0
        median = statistics.median(prices) if prices else 0.0
        standard_deviation = statistics.pstdev(prices) if len(prices) > 1 else 0.0
        previous = prices[-2] if len(prices) >= 2 else 0.0
        variation = self.variation(current, previous)
        percentile = (
            (sum(price <= current for price in prices) / count) * 100
            if current > 0 and count else None
        )
        near_low = bool(
            reliable and current > 0 and minimum > 0
            and current <= minimum * (
                1 + self.policy.history_near_low_percent / 100
            )
        )
        daily = self.period_variation(observations, 1)
        weekly = self.period_variation(observations, 7)
        monthly = self.period_variation(observations, 30)
        trend = self.trend(daily)
        previous_minimum = min(prices[:-1]) if len(prices) > 1 else 0.0
        is_new_record = bool(
            reliable and current > 0 and previous_minimum > 0
            and current < previous_minimum
        )
        drop_percent = max(
            -value for value in (daily, weekly, monthly)
            if value is not None and value < 0
        ) if any(
            value is not None and value < 0 for value in (daily, weekly, monthly)
        ) else 0.0
        events = self.events(
            reliable, current, minimum, average, is_new_record, drop_percent
        )
        span_days = (
            (observations[-1].observed_at.date()
             - observations[0].observed_at.date()).days
            if len(observations) >= 2 else 0
        )
        return OfferHistoryResult(
            identity=identity,
            minimum=round(minimum, 2),
            maximum=round(maximum, 2),
            average=round(average, 2),
            median=round(float(median), 2),
            sample_count=count,
            reliable=reliable,
            is_historical_low=bool(
                reliable and current > 0 and current <= minimum
            ),
            is_near_historical_low=near_low,
            variation_from_previous_percent=self.round_optional(variation),
            percentile=self.round_optional(percentile),
            observations=observations,
            standard_deviation=round(standard_deviation, 2),
            observed_days=observed_days,
            first_price=round(prices[0], 2) if prices else 0.0,
            last_price=round(prices[-1], 2) if prices else 0.0,
            daily_variation_percent=self.round_optional(daily),
            weekly_variation_percent=self.round_optional(weekly),
            monthly_variation_percent=self.round_optional(monthly),
            trend=trend,
            is_new_record=is_new_record,
            drop_percent=round(drop_percent, 2),
            events=events,
            temporal_confidence=self.temporal_confidence(observed_days),
            history_span_days=span_days,
        )

    @staticmethod
    def variation(current, reference):
        if current <= 0 or reference <= 0:
            return None
        value = ((current - reference) / reference) * 100
        return value if math.isfinite(value) else None

    @classmethod
    def period_variation(cls, observations, days):
        if len(observations) < 2:
            return None
        latest = observations[-1]
        target = latest.observed_at - timedelta(days=days)
        eligible = [
            item for item in observations[:-1]
            if item.observed_at <= target
        ]
        if not eligible:
            return None
        return cls.variation(
            OfferScore.number(latest.price),
            OfferScore.number(eligible[-1].price),
        )

    @staticmethod
    def trend(variation):
        if variation is None or abs(variation) < 1:
            return "estavel"
        return "caiu" if variation < 0 else "subiu"

    @staticmethod
    def events(reliable, current, minimum, average, is_new_record, drop):
        events = []
        if reliable and current > 0 and current <= minimum:
            events.append("menor_preco_historico")
        if is_new_record:
            events.append("novo_recorde_preco")
        for threshold in (5, 10, 20, 30):
            if drop >= threshold:
                events.append(f"queda_{threshold}_porcento")
        if reliable and average > 0 and current < average:
            events.append("abaixo_da_media_historica")
        return tuple(events)

    @staticmethod
    def temporal_confidence(observed_days):
        if observed_days >= 90:
            return "maxima"
        if observed_days >= 30:
            return "muito_alta"
        if observed_days >= 15:
            return "alta"
        if observed_days >= 7:
            return "boa"
        if observed_days >= 3:
            return "media"
        return "baixa"

    def minimum_price(self, identity):
        result = self.analyze(identity)
        return result.minimum

    def maximum_price(self, identity):
        return self.analyze(identity).maximum

    def average_price(self, identity):
        return self.analyze(identity).average

    @staticmethod
    def round_optional(value):
        return (
            round(value, 2)
            if value is not None and math.isfinite(value) else None
        )

    @staticmethod
    def normalize_datetime(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
