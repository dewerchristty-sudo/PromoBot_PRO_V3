from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class MonitorExecution:
    execution_id: str
    monitor_id: int
    search_term: str
    started_at: str
    configured_stores_json: str
    finished_at: Optional[str] = None
    duration_ms: Optional[float] = None
    aggregate_total: Optional[int] = None
    status: str = "running"


@dataclass(frozen=True)
class MonitorStoreRun:
    execution_id: str
    store_name: str
    started_at: str
    finished_at: str
    duration_ms: float
    returned_count: Optional[int]
    sanitized_count: Optional[int]
    aggregate_added_count: Optional[int]
    status: str
    error_type: Optional[str] = None
    sanitized_error: Optional[str] = None
