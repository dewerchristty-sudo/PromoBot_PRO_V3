import unittest
import threading
import time
from datetime import datetime, timedelta
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


if __name__ == "__main__":
    unittest.main()
