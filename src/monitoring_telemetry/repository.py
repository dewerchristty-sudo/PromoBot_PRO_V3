import sqlite3
import threading
from pathlib import Path

from src.monitoring_telemetry.models import (
    MonitorExecution,
    MonitorStoreRun,
)


class MonitorTelemetryRepository:
    def __init__(self, database_path="monitor_telemetry.db"):
        self.database_path = Path(database_path)
        self.connection = sqlite3.connect(
            self.database_path,
            check_same_thread=False,
        )
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.lock = threading.RLock()
        self.closed = False

    def migrate(self):
        migration = (
            Path(__file__).resolve().parent
            / "migrations"
            / "001_monitor_telemetry.sql"
        ).read_text(encoding="utf-8")
        with self.lock:
            self.connection.executescript(migration)
            self.connection.commit()

    def start_execution(self, execution):
        with self.lock:
            self.connection.execute("""
                INSERT INTO monitor_execution_runs(
                    execution_id,
                    monitor_id,
                    search_term,
                    started_at,
                    configured_stores_json,
                    status
                )
                VALUES(?,?,?,?,?,?)
            """, (
                execution.execution_id,
                execution.monitor_id,
                execution.search_term,
                execution.started_at,
                execution.configured_stores_json,
                execution.status,
            ))
            self.connection.commit()

    def finish_execution(
        self,
        execution_id,
        finished_at,
        duration_ms,
        aggregate_total,
        status,
    ):
        with self.lock:
            self.connection.execute("""
                UPDATE monitor_execution_runs
                SET finished_at = ?,
                    duration_ms = ?,
                    aggregate_total = ?,
                    status = ?
                WHERE execution_id = ?
            """, (
                finished_at,
                duration_ms,
                aggregate_total,
                status,
                execution_id,
            ))
            self.connection.commit()

    def add_store_run(self, store_run):
        with self.lock:
            self.connection.execute("""
                INSERT INTO monitor_store_runs(
                    execution_id,
                    store_name,
                    started_at,
                    finished_at,
                    duration_ms,
                    returned_count,
                    sanitized_count,
                    aggregate_added_count,
                    status,
                    error_type,
                    sanitized_error
                )
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """, (
                store_run.execution_id,
                store_run.store_name,
                store_run.started_at,
                store_run.finished_at,
                store_run.duration_ms,
                store_run.returned_count,
                store_run.sanitized_count,
                store_run.aggregate_added_count,
                store_run.status,
                store_run.error_type,
                store_run.sanitized_error,
            ))
            self.connection.commit()

    def get_execution(self, execution_id):
        with self.lock:
            row = self.connection.execute("""
                SELECT * FROM monitor_execution_runs
                WHERE execution_id = ?
            """, (execution_id,)).fetchone()
        return MonitorExecution(**dict(row)) if row else None

    def store_runs_for(self, execution_id):
        with self.lock:
            rows = self.connection.execute("""
                SELECT execution_id, store_name, started_at, finished_at,
                       duration_ms, returned_count, sanitized_count,
                       aggregate_added_count, status, error_type,
                       sanitized_error
                FROM monitor_store_runs
                WHERE execution_id = ?
                ORDER BY id
            """, (execution_id,)).fetchall()
        return tuple(MonitorStoreRun(**dict(row)) for row in rows)

    def close(self):
        with self.lock:
            if not self.closed:
                self.connection.close()
                self.closed = True
