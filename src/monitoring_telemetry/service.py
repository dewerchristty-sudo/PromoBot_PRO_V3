import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from src.monitoring_telemetry.error_classifier import (
    classify_error,
    sanitize_error_message,
)
from src.monitoring_telemetry.models import (
    MonitorExecution,
    MonitorStoreRun,
)
from src.monitoring_telemetry.repository import MonitorTelemetryRepository


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class MonitorStoreTelemetryObserver:
    def __init__(self, service, execution_id):
        self.service = service
        self.execution_id = execution_id

    def record_store(
        self,
        *,
        store_name,
        started_at,
        finished_at,
        duration_ms,
        returned_count,
        sanitized_count,
        aggregate_added_count,
        status,
        error=None,
        error_type=None,
    ):
        self.service.record_store(
            MonitorStoreRun(
                execution_id=self.execution_id,
                store_name=str(store_name or ""),
                started_at=started_at,
                finished_at=finished_at,
                duration_ms=max(float(duration_ms), 0.0),
                returned_count=returned_count,
                sanitized_count=sanitized_count,
                aggregate_added_count=aggregate_added_count,
                status=str(status or "unknown_error"),
                error_type=error_type or classify_error(error),
                sanitized_error=(
                    sanitize_error_message(error) if error else None
                ),
            )
        )


class MonitorTelemetryService:
    def __init__(self, repository):
        self.repository = repository
        self.execution_started = {}
        self.closed = False

    @classmethod
    def from_environment(cls):
        enabled = os.getenv(
            "ENABLE_MONITOR_TELEMETRY",
            "false",
        ).strip().casefold() in {"1", "true", "yes", "on", "sim"}
        if not enabled:
            return None
        try:
            path = Path(
                os.getenv(
                    "MONITOR_TELEMETRY_DB_PATH",
                    "monitor_telemetry.db",
                )
            )
            repository = MonitorTelemetryRepository(path)
            repository.migrate()
            return cls(repository)
        except Exception:
            return None

    def start_execution(self, monitor_id, search_term, configured_stores):
        execution_id = uuid4().hex
        started_at = utc_now()
        self.execution_started[execution_id] = time.perf_counter()
        execution = MonitorExecution(
            execution_id=execution_id,
            monitor_id=int(monitor_id),
            search_term=sanitize_error_message(search_term),
            started_at=started_at,
            configured_stores_json=json.dumps(
                [
                    sanitize_error_message(store)
                    for store in (configured_stores or ())
                ],
                ensure_ascii=False,
            ),
        )
        try:
            self.repository.start_execution(execution)
            return execution_id
        except Exception:
            self.execution_started.pop(execution_id, None)
            return None

    def store_observer(self, execution_id):
        if not execution_id:
            return None
        return MonitorStoreTelemetryObserver(self, execution_id)

    def record_store(self, store_run):
        try:
            self.repository.add_store_run(store_run)
            return True
        except Exception:
            return False

    def finish_execution(self, execution_id, aggregate_total, status):
        if not execution_id:
            return False
        started = self.execution_started.pop(execution_id, None)
        duration_ms = (
            (time.perf_counter() - started) * 1000
            if started is not None else None
        )
        try:
            self.repository.finish_execution(
                execution_id,
                utc_now(),
                duration_ms,
                aggregate_total,
                status,
            )
            return True
        except Exception:
            return False

    def close(self):
        if not self.closed:
            try:
                self.repository.close()
            except Exception:
                pass
            self.closed = True
