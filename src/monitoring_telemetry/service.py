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
        self.execution_store_statuses = {}
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
        self.execution_store_statuses[execution_id] = []
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
            self.execution_store_statuses.pop(execution_id, None)
            return None

    def store_observer(self, execution_id):
        if not execution_id:
            return None
        return MonitorStoreTelemetryObserver(self, execution_id)

    def record_store(self, store_run):
        self.execution_store_statuses.setdefault(
            store_run.execution_id,
            [],
        ).append(store_run.status)
        try:
            self.repository.add_store_run(store_run)
            return True
        except Exception:
            return False

    def finish_execution(self, execution_id, aggregate_total, status):
        if not execution_id:
            return False
        started = self.execution_started.pop(execution_id, None)
        store_statuses = self.execution_store_statuses.pop(execution_id, [])
        duration_ms = (
            (time.perf_counter() - started) * 1000
            if started is not None else None
        )
        final_status = self.final_execution_status(
            store_statuses,
            aggregate_total,
            status,
        )
        try:
            self.repository.finish_execution(
                execution_id,
                utc_now(),
                duration_ms,
                aggregate_total,
                final_status,
            )
            return True
        except Exception:
            return False

    @staticmethod
    def final_execution_status(store_statuses, aggregate_total, fallback):
        if fallback == "failed":
            return "failed"
        if not store_statuses:
            return fallback

        failures = sum(status == "error" for status in store_statuses)
        if failures == len(store_statuses):
            return "failed"
        if failures:
            return "partial_success"
        if (aggregate_total or 0) == 0:
            return "zero_results"
        return "success"

    def close(self):
        if not self.closed:
            try:
                self.repository.close()
            except Exception:
                pass
            self.closed = True
