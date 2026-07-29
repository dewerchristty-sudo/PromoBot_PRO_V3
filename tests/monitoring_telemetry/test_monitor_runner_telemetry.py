import unittest
from unittest.mock import Mock, patch

from src.core.monitor import MonitorRunner
from src.monitoring_telemetry.service import MonitorTelemetryService


class MonitorRunnerTelemetryTest(unittest.TestCase):

    @staticmethod
    def database():
        database = Mock()
        database.alertas_pendentes.return_value = []
        database.listar_fila_notificacoes.return_value = []
        return database

    @staticmethod
    def monitoring():
        return {
            "id": 7,
            "termo": "air fryer",
            "lojas": "Mercado Livre,Amazon,Shopee",
        }

    def test_disabled_telemetry_keeps_last_total(self):
        database = self.database()
        runner = MonitorRunner(database, telemetry_service=None)
        runner.telemetry_service = None
        products = [{"loja": "Mercado Livre"}] * 15
        with patch("src.core.monitor.StoreManager") as manager_class:
            manager_class.return_value.search_all.return_value = products
            total = runner.execute_monitoring(self.monitoring())
        self.assertEqual(total, 15)
        database.registrar_execucao_monitoramento.assert_called_once_with(
            7, 15
        )

    def test_records_execution_without_changing_total(self):
        database = self.database()
        telemetry = Mock()
        telemetry.start_execution.return_value = "execution-1"
        observer = Mock()
        telemetry.store_observer.return_value = observer
        runner = MonitorRunner(database, telemetry_service=telemetry)
        products = [{"loja": "Mercado Livre"}] * 3
        with patch("src.core.monitor.StoreManager") as manager_class:
            manager_class.return_value.search_all.return_value = products
            total = runner.execute_monitoring(self.monitoring())
        self.assertEqual(total, 3)
        database.registrar_execucao_monitoramento.assert_called_once_with(
            7, 3
        )
        telemetry.finish_execution.assert_called_once_with(
            "execution-1", 3, "success"
        )
        self.assertIs(
            manager_class.call_args.kwargs["telemetry_observer"],
            observer,
        )

    def test_telemetry_start_failure_does_not_interrupt_monitor(self):
        database = self.database()
        telemetry = Mock()
        telemetry.start_execution.side_effect = RuntimeError("offline")
        runner = MonitorRunner(database, telemetry_service=telemetry)
        with patch("src.core.monitor.StoreManager") as manager_class:
            manager_class.return_value.search_all.return_value = []
            total = runner.execute_monitoring(self.monitoring())
        self.assertEqual(total, 0)
        database.registrar_execucao_monitoramento.assert_called_once_with(
            7, 0
        )

    def test_original_monitor_failure_is_not_hidden(self):
        database = self.database()
        telemetry = Mock()
        telemetry.start_execution.return_value = "execution-1"
        telemetry.store_observer.return_value = Mock()
        telemetry.finish_execution.side_effect = RuntimeError("offline")
        runner = MonitorRunner(database, telemetry_service=telemetry)
        with patch("src.core.monitor.StoreManager") as manager_class:
            manager_class.return_value.search_all.side_effect = ValueError(
                "original collection error"
            )
            with self.assertRaisesRegex(
                ValueError, "original collection error"
            ):
                runner.execute_monitoring(self.monitoring())

    def test_default_false_does_not_create_telemetry_database(self):
        with patch.dict("os.environ", {
            "ENABLE_MONITOR_TELEMETRY": "false",
        }, clear=False):
            runner = MonitorRunner(self.database())
        self.assertIsNone(runner.telemetry_service)

    def test_final_execution_statuses(self):
        cases = (
            (["success"], 3, "success"),
            (["success", "error"], 3, "partial_success"),
            (["zero_results", "filtered_out"], 0, "zero_results"),
            (["error", "error"], 0, "failed"),
        )
        for store_statuses, total, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(
                    MonitorTelemetryService.final_execution_status(
                        store_statuses,
                        total,
                        "success",
                    ),
                    expected,
                )

    def test_telemetry_enabled_and_disabled_keep_same_functional_result(self):
        products = [{"loja": "Mercado Livre"}] * 2
        totals = []

        for telemetry in (None, Mock()):
            database = self.database()
            runner = MonitorRunner(database, telemetry_service=telemetry)
            runner.telemetry_service = telemetry
            if telemetry is not None:
                telemetry.start_execution.return_value = "execution-1"
                telemetry.store_observer.return_value = Mock()
            with patch("src.core.monitor.StoreManager") as manager_class:
                manager_class.return_value.search_all.return_value = products
                manager_class.return_value.stores = []
                totals.append(runner.execute_monitoring(self.monitoring()))
            database.registrar_execucao_monitoramento.assert_called_once_with(
                7,
                2,
            )

        self.assertEqual(totals, [2, 2])


if __name__ == "__main__":
    unittest.main()
