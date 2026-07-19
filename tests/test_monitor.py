import unittest
import threading
import time
from unittest.mock import Mock

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


if __name__ == "__main__":
    unittest.main()
