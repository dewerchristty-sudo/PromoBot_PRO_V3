from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from src.monitoring_telemetry.repository import MonitorTelemetryRepository
from src.monitoring_telemetry.service import MonitorTelemetryService


class MonitorTelemetryServiceTest(unittest.TestCase):

    def test_disabled_flag_does_not_create_database(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "monitor_telemetry.db"
            with patch.dict("os.environ", {
                "ENABLE_MONITOR_TELEMETRY": "false",
                "MONITOR_TELEMETRY_DB_PATH": str(path),
            }, clear=False):
                service = MonitorTelemetryService.from_environment()
            self.assertIsNone(service)
            self.assertFalse(path.exists())

    def test_enabled_flag_uses_separate_database(self):
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "monitor_telemetry.db"
            with patch.dict("os.environ", {
                "ENABLE_MONITOR_TELEMETRY": "true",
                "MONITOR_TELEMETRY_DB_PATH": str(path),
            }, clear=False):
                service = MonitorTelemetryService.from_environment()
            self.assertIsNotNone(service)
            self.assertTrue(path.exists())
            service.close()

    def test_records_complete_execution(self):
        with TemporaryDirectory() as temporary:
            repository = MonitorTelemetryRepository(
                Path(temporary) / "telemetry.db"
            )
            repository.migrate()
            service = MonitorTelemetryService(repository)
            execution_id = service.start_execution(
                1,
                "air fryer",
                ["Mercado Livre", "Amazon"],
            )
            observer = service.store_observer(execution_id)
            observer.record_store(
                store_name="Amazon",
                started_at="start",
                finished_at="finish",
                duration_ms=5,
                returned_count=None,
                sanitized_count=None,
                aggregate_added_count=0,
                status="error",
                error=RuntimeError("HTTP 503"),
            )
            self.assertTrue(service.finish_execution(
                execution_id,
                15,
                "success",
            ))

            execution = repository.get_execution(execution_id)
            store = repository.store_runs_for(execution_id)[0]
            self.assertEqual(execution.aggregate_total, 15)
            self.assertEqual(store.error_type, "http_503")
            service.close()

    def test_repository_failure_is_non_blocking(self):
        repository = Mock()
        repository.start_execution.side_effect = RuntimeError("offline")
        service = MonitorTelemetryService(repository)
        self.assertIsNone(service.start_execution(1, "produto", ["Amazon"]))

        repository.add_store_run.side_effect = RuntimeError("offline")
        store_run = Mock()
        self.assertFalse(service.record_store(store_run))

        repository.finish_execution.side_effect = RuntimeError("offline")
        self.assertFalse(service.finish_execution("missing", 0, "failed"))

    def test_search_term_does_not_persist_sensitive_link_or_phone(self):
        with TemporaryDirectory() as temporary:
            repository = MonitorTelemetryRepository(
                Path(temporary) / "telemetry.db"
            )
            repository.migrate()
            service = MonitorTelemetryService(repository)
            execution_id = service.start_execution(
                1,
                "produto https://example.com/item?token=x 5511999999999",
                ["Amazon"],
            )
            stored = repository.get_execution(execution_id)
            self.assertNotIn("token=x", stored.search_term)
            self.assertNotIn("5511999999999", stored.search_term)
            service.close()


if __name__ == "__main__":
    unittest.main()
