from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True)
class GroupCount:
    label: str
    total: int


@dataclass(frozen=True)
class CoverageCount:
    items: tuple[GroupCount, ...] = ()
    covered: int = 0
    total: int = 0

    @property
    def percentage(self):
        return (self.covered / self.total * 100) if self.total else 0.0


@dataclass(frozen=True)
class CoverageAverage:
    average: float = 0.0
    covered: int = 0
    total: int = 0

    @property
    def percentage(self):
        return (self.covered / self.total * 100) if self.total else 0.0


@dataclass(frozen=True)
class RecentSend:
    store: str
    title: str
    channel: str
    status: str
    sent_at: str


@dataclass(frozen=True)
class TimeSeriesPoint:
    period: str
    total: int


@dataclass(frozen=True)
class StatisticsSnapshot:
    total_products: int = 0
    total_sends: int = 0
    pending_reviews: int = 0
    active_alerts: int = 0
    failed_deliveries: int = 0
    products_by_store: tuple[GroupCount, ...] = ()
    sends_by_channel: tuple[GroupCount, ...] = ()
    most_sent_products: tuple[GroupCount, ...] = ()
    recent_sends: tuple[RecentSend, ...] = ()
    daily_collections: tuple[TimeSeriesPoint, ...] = ()
    daily_sends: tuple[TimeSeriesPoint, ...] = ()
    weekly_collections: tuple[TimeSeriesPoint, ...] = ()
    weekly_sends: tuple[TimeSeriesPoint, ...] = ()
    products_by_category: CoverageCount = field(default_factory=CoverageCount)
    sent_categories: CoverageCount = field(default_factory=CoverageCount)
    average_discount: CoverageAverage = field(default_factory=CoverageAverage)
    average_savings: CoverageAverage = field(default_factory=CoverageAverage)
    generated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
