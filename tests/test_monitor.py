import unittest
import threading
import time
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from src.core.monitor import MonitorRunner


class MonitorRunnerTest(unittest.TestCase):

    def make_idle_database(self):

        database = Mock()
        database.listar_monitoramentos.return_value = []
        database.alertas_pendentes.return_value = []
        database.listar_fila_notificacoes.return_value = []
        return database

    def test_run_once_notifica_pendentes_antes_de_buscar(self):

        eventos = []
        database = Mock()
        alerts = [
            {
                "alerta_id": 1,
                "link": "https://example.com/produto",
                "loja": "Amazon",
                "titulo": "Produto em oferta",
                "preco_valor": 99.9,
            }
        ]
        database.alertas_pendentes.side_effect = [alerts, []]
        database.listar_monitoramentos.return_value = [
            {
                "id": 1,
                "termo": "oferta",
                "lojas": "Amazon",
            }
        ]

        runner = MonitorRunner(database)
        runner.notifier = Mock()
        runner.notifier.send_alerts.side_effect = lambda *_: eventos.append(
            "notificou"
        ) or "Enviado por: WhatsApp"
        runner.execute_monitoring = Mock(
            side_effect=lambda *_: eventos.append("buscou") or 1
        )

        total = runner.run_once()

        self.assertEqual(total, 1)
        self.assertEqual(eventos[0], "notificou")
        self.assertEqual(eventos[1], "buscou")

    def test_stop_aguarda_thread_do_monitor(self):

        runner = MonitorRunner(self.make_idle_database())
        runner.start()
        runner.stop()

        self.assertFalse(runner.running)
        self.assertFalse(runner.thread.is_alive())
        runner.shutdown()

    def test_monitoramento_nunca_executado_esta_devido(self):

        self.assertTrue(MonitorRunner.monitoramento_devido({
            "ultima_execucao": None,
            "intervalo_minutos": 240,
        }))

    def test_monitoramento_respeita_intervalo_individual(self):

        agora = datetime(2026, 7, 19, 20, 0, 0)
        recente = {
            "ultima_execucao": (agora - timedelta(minutes=30)).isoformat(
                sep=" "
            ),
            "intervalo_minutos": 240,
        }
        antigo = {
            "ultima_execucao": (agora - timedelta(minutes=241)).isoformat(
                sep=" "
            ),
            "intervalo_minutos": 240,
        }

        self.assertFalse(MonitorRunner.monitoramento_devido(recente, agora))
        self.assertTrue(MonitorRunner.monitoramento_devido(antigo, agora))

    def test_lote_executa_no_maximo_dois_monitores(self):

        database = self.make_idle_database()
        database.listar_monitoramentos.return_value = [
            {
                "id": index,
                "ultima_execucao": None,
                "intervalo_minutos": 240,
            }
            for index in range(1, 6)
        ]
        runner = MonitorRunner(database)
        runner.execute_monitoring = Mock(return_value=1)

        total = runner.run_due_batch()

        self.assertEqual(total, 2)
        self.assertEqual(runner.execute_monitoring.call_count, 2)

    def test_shutdown_aguarda_execucao_manual(self):

        runner = MonitorRunner(self.make_idle_database())
        iniciou = threading.Event()
        liberar = threading.Event()

        def execucao():
            with runner.execution_lock:
                iniciou.set()
                liberar.wait(1)

        worker = threading.Thread(target=execucao)
        worker.start()
        self.assertTrue(iniciou.wait(1))

        shutdown = threading.Thread(target=runner.shutdown)
        shutdown.start()
        time.sleep(0.02)
        self.assertTrue(shutdown.is_alive())

        liberar.set()
        shutdown.join(1)
        worker.join(1)
        self.assertFalse(shutdown.is_alive())

    def test_shutdown_aguarda_notificacao_assincrona(self):

        runner = MonitorRunner(self.make_idle_database())
        iniciou = threading.Event()
        liberar = threading.Event()

        def notificacao():
            iniciou.set()
            liberar.wait(1)

        runner.notify_pending_alerts = notificacao
        runner.notify_pending_async()
        self.assertTrue(iniciou.wait(1))

        shutdown = threading.Thread(target=runner.shutdown)
        shutdown.start()
        time.sleep(0.02)
        self.assertTrue(shutdown.is_alive())

        liberar.set()
        shutdown.join(1)
        self.assertFalse(shutdown.is_alive())

    def test_shutdown_tem_limite_quando_execucao_nao_responde(self):

        runner = MonitorRunner(self.make_idle_database())
        iniciou = threading.Event()
        liberar = threading.Event()

        def execucao_lenta():
            with runner.execution_lock:
                iniciou.set()
                liberar.wait(1)

        worker = threading.Thread(target=execucao_lenta, daemon=True)
        worker.start()
        self.assertTrue(iniciou.wait(1))

        started = time.monotonic()
        clean = runner.shutdown(timeout=0.02)
        elapsed = time.monotonic() - started

        self.assertFalse(clean)
        self.assertLess(elapsed, 0.5)
        liberar.set()
        worker.join(1)

    @staticmethod
    def monitoring():
        return {
            "id": 7,
            "termo": "air fryer",
            "lojas": "Mercado Livre,Amazon,Shopee",
        }

    def test_execute_monitoring_closes_all_stores_after_success(self):
        database = self.make_idle_database()
        runner = MonitorRunner(database)
        stores = [Mock(), Mock(), Mock()]

        with patch("src.core.monitor.StoreManager") as manager_class:
            manager_class.return_value.stores = stores
            manager_class.return_value.search_all.return_value = [{"id": 1}]
            self.assertEqual(runner.execute_monitoring(self.monitoring()), 1)

        for store in stores:
            store.close.assert_called_once_with()

    def test_execute_monitoring_closes_all_stores_after_error(self):
        database = self.make_idle_database()
        database.salvar_lista.side_effect = RuntimeError("database unavailable")
        runner = MonitorRunner(database)
        stores = [Mock(), Mock(), Mock()]

        with patch("src.core.monitor.StoreManager") as manager_class:
            manager_class.return_value.stores = stores
            manager_class.return_value.search_all.return_value = [{"id": 1}]
            with self.assertRaisesRegex(RuntimeError, "database unavailable"):
                runner.execute_monitoring(self.monitoring())

        for store in stores:
            store.close.assert_called_once_with()

    def test_close_error_is_non_blocking_and_repeated_close_is_tolerated(self):
        first = Mock()
        first.close.side_effect = RuntimeError("close failed")
        second = Mock()
        manager = Mock(stores=[first, second])

        MonitorRunner.close_store_resources(manager)
        MonitorRunner.close_store_resources(manager)

        self.assertEqual(first.close.call_count, 2)
        self.assertEqual(second.close.call_count, 2)

    def test_five_consecutive_executions_close_playwright_resources(self):
        database = self.make_idle_database()
        runner = MonitorRunner(database)
        active_resource = {"open": False}
        managers = []

        def build_manager(**_kwargs):
            if active_resource["open"]:
                raise RuntimeError(
                    "Playwright Sync API inside the asyncio loop"
                )
            store = Mock()
            store.close.side_effect = lambda: active_resource.update(open=False)
            manager = Mock(stores=[store])
            manager.search_all.side_effect = lambda _term: (
                active_resource.update(open=True) or [{"id": 1}]
            )
            managers.append(manager)
            return manager

        with patch("src.core.monitor.StoreManager", side_effect=build_manager):
            totals = [
                runner.execute_monitoring(self.monitoring())
                for _ in range(5)
            ]

        self.assertEqual(totals, [1, 1, 1, 1, 1])
        self.assertFalse(active_resource["open"])
        self.assertEqual(
            [manager.stores[0].close.call_count for manager in managers],
            [1, 1, 1, 1, 1],
        )

    def test_manual_and_automatic_runs_do_not_execute_simultaneously(self):
        runner = MonitorRunner(self.make_idle_database())
        first_started = threading.Event()
        release_first = threading.Event()
        second_started = threading.Event()

        def run_cycle():
            if not first_started.is_set():
                first_started.set()
                release_first.wait(1)
            else:
                second_started.set()
            return 0

        runner._run_once_unlocked = run_cycle
        automatic = threading.Thread(target=runner.run_once)
        manual = threading.Thread(target=runner.run_once)
        automatic.start()
        self.assertTrue(first_started.wait(1))
        manual.start()
        self.assertFalse(second_started.wait(0.05))
        release_first.set()
        automatic.join(1)
        manual.join(1)
        self.assertTrue(second_started.is_set())


if __name__ == "__main__":
    unittest.main()
