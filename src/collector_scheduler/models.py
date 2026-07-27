from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True, slots=True)
class SchedulerValidation:
    valid: bool
    status: str
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class CollectionRunResult:
    status: str
    started_at: datetime
    ended_at: datetime
    next_run: datetime | None
    products: int
    valid_observations: int
    duplicates: int
    failures: int
    retries: int
    duration_seconds: float
    errors: tuple[str, ...] = ()
    details: tuple[dict, ...] = field(default_factory=tuple)
