import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from src.monitoring_telemetry.models import (
    MonitorExecution,
    MonitorStoreRun,
)
from src.monitoring_telemetry.repository import MonitorTelemetryRepository


class MonitorTelemetryRepositoryTest(unittest.TestCase):

    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.path = Path(self.temporary.name) / "telemetry.db"

    def tearDown(self):
        self.temporary.cleanup()

    def repository(self):
        repository = MonitorTelemetryRepository(self.path)
        repository.migrate()
        return repository

    def test_migration_creates_only_phase_one_tables(self):
        repository = self.repository()
        tables = {
            row[0] for row in repository.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        repository.close()
        self.assertIn("monitor_execution_runs", tables)
        self.assertIn("monitor_store_runs", tables)
        self.assertNotIn("entregas_destino", tables)
        self.assertNotIn("historico_envios", tables)

    def test_migration_is_idempotent(self):
        repository = self.repository()
        repository.migrate()
        repository.migrate()
        self.assertEqual(
            repository.connection.execute(
                "PRAGMA integrity_check"
            ).fetchone()[0],
            "ok",
        )
        repository.close()

    def test_records_execution_and_nullable_store_counts(self):
        repository = self.repository()
        execution = MonitorExecution(
            execution_id="execution-1",
            monitor_id=7,
            search_term="air fryer",
            started_at="2026-07-29T12:00:00+00:00",
            configured_stores_json='["Amazon"]',
        )
        repository.start_execution(execution)
        repository.add_store_run(MonitorStoreRun(
            execution_id="execution-1",
            store_name="Amazon",
            started_at="2026-07-29T12:00:00+00:00",
            finished_at="2026-07-29T12:00:01+00:00",
            duration_ms=1000,
            returned_count=None,
            sanitized_count=None,
            aggregate_added_count=0,
            status="error",
            error_type="http_503",
            sanitized_error="HTTP 503",
        ))
        repository.finish_execution(
            "execution-1",
            "2026-07-29T12:00:01+00:00",
            1000,
            0,
            "success",
        )

        stored = repository.get_execution("execution-1")
        stores = repository.store_runs_for("execution-1")
        repository.close()

        self.assertEqual(stored.aggregate_total, 0)
        self.assertEqual(stored.status, "success")
        self.assertIsNone(stores[0].returned_count)
        self.assertEqual(stores[0].aggregate_added_count, 0)

    def test_foreign_key_rejects_orphan_store_run(self):
        repository = self.repository()
        with self.assertRaises(sqlite3.IntegrityError):
            repository.add_store_run(MonitorStoreRun(
                execution_id="missing",
                store_name="Shopee",
                started_at="start",
                finished_at="finish",
                duration_ms=1,
                returned_count=0,
                sanitized_count=0,
                aggregate_added_count=0,
                status="zero_results",
                error_type="zero_results",
            ))
        repository.close()

    def test_repository_is_separate_from_main_database(self):
        repository = self.repository()
        repository.close()
        self.assertEqual(self.path.name, "telemetry.db")
        self.assertTrue(self.path.exists())


if __name__ == "__main__":
    unittest.main()
