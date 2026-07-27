"""
Testes de integração para o sistema completo de monitoramento.

Cobre a integração entre:
    - MonitorManager
    - MonitorScheduler
    - ProductWatcherManager
    - ProductWatcher
    - Scheduler

Verifica:
    - start_all / stop_all
    - Thread safety
    - Parada segura
    - Limpeza de recursos
    - Execução duplicada
    - Callbacks executados apenas quando ativo
    - Exceções de um monitor não interrompem os demais
    - Logs de execução
"""

from __future__ import annotations

import logging
import threading
import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from src.monitor.monitor_manager import MonitorManager, MonitorStats
from src.monitor.scheduler import MonitorScheduler, Scheduler
from src.monitor.watcher import ProductWatcher, ProductWatcherManager, WatcherStatus


class TestMonitorIntegration(unittest.TestCase):
    """Testes de integração do sistema de monitoramento completo."""

    def setUp(self) -> None:
        self.manager = MonitorManager(poll_interval_seconds=0.01)

    def tearDown(self) -> None:
        if self.manager.is_running:
            self.manager.stop_all(wait=True)

    # ── start_all / stop_all ────────────────────────────────────────

    def test_start_all_inicia_todos_os_componentes(self) -> None:
        """start_all inicia MonitorManager e ProductWatcherManager."""
        self.assertFalse(self.manager.is_running)
        self.assertFalse(self.manager._watcher_manager.is_running)

        self.manager.start_all()

        self.assertTrue(self.manager.is_running)
        self.assertTrue(self.manager._watcher_manager.is_running)

        self.manager.stop_all()

    def test_stop_all_para_todos_os_componentes(self) -> None:
        """stop_all para MonitorManager e ProductWatcherManager."""
        self.manager.start_all()
        self.assertTrue(self.manager.is_running)
        self.assertTrue(self.manager._watcher_manager.is_running)

        self.manager.stop_all(wait=True)

        self.assertFalse(self.manager.is_running)
        self.assertFalse(self.manager._watcher_manager.is_running)

    def test_start_all_duas_vezes_nao_gera_erro(self) -> None:
        """start_all duas vezes é seguro (no-op)."""
        self.manager.start_all()
        self.manager.start_all()  # não deve levantar exceção
        self.assertTrue(self.manager.is_running)
        self.manager.stop_all()

    def test_stop_all_sem_iniciar_nao_gera_erro(self) -> None:
        """stop_all sem start_all não gera erro."""
        self.manager.stop_all()  # não deve levantar exceção
        self.assertFalse(self.manager.is_running)

    def test_start_stop_all_multiplas_vezes(self) -> None:
        """start_all e stop_all múltiplas vezes."""
        for _ in range(3):
            self.manager.start_all()
            self.assertTrue(self.manager.is_running)
            self.assertTrue(self.manager._watcher_manager.is_running)
            self.manager.stop_all(wait=True)
            self.assertFalse(self.manager.is_running)
            self.assertFalse(self.manager._watcher_manager.is_running)

    # ── registro e verificação integrada ────────────────────────────

    def test_registro_e_verificacao_integrada(self) -> None:
        """Produto registrado é verificado via ProductWatcherManager."""
        callback = Mock()
        self.manager.set_on_due_callback(callback)

        self.manager.register_product(
            "p1", "https://example.com/p1", "Amazon",
            interval_minutes=1,
        )
        # Força o watcher a ficar devido
        watcher = self.manager.get_product("p1")
        watcher.last_check = datetime.now() - timedelta(minutes=10)

        self.manager.start_all()
        time.sleep(0.3)
        self.manager.stop_all()

        # O callback deve ter sido chamado
        self.assertTrue(callback.called)

    def test_callback_nao_executado_apos_stop_all(self) -> None:
        """Callback não é executado após stop_all."""
        callback = Mock()
        self.manager.set_on_due_callback(callback)

        self.manager.register_product(
            "p1", "https://example.com/p1", "Amazon",
            interval_minutes=1,
        )
        watcher = self.manager.get_product("p1")
        watcher.last_check = datetime.now() - timedelta(minutes=10)

        self.manager.start_all()
        time.sleep(0.2)
        chamadas_ate_parar = callback.call_count
        self.manager.stop_all(wait=True)

        time.sleep(0.3)
        # Não deve ter chamado novamente após parar
        self.assertEqual(callback.call_count, chamadas_ate_parar)

    # ── thread safety ───────────────────────────────────────────────

    def test_thread_safety_start_stop_concorrente(self) -> None:
        """start_all e stop_all concorrentes são thread-safe."""
        erros: list[Exception] = []
        lock = threading.Lock()

        def operacao() -> None:
            try:
                for _ in range(5):
                    self.manager.start_all()
                    time.sleep(0.05)
                    self.manager.stop_all(wait=True)
            except Exception as e:
                with lock:
                    erros.append(e)

        threads = [threading.Thread(target=operacao) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(erros), 0)

    def test_thread_safety_registro_concorrente(self) -> None:
        """Registro concorrente de produtos é thread-safe."""
        erros: list[Exception] = []
        lock = threading.Lock()

        def registrar(i: int) -> None:
            try:
                self.manager.register_product(
                    f"p{i}", f"https://example.com/p{i}", "Amazon",
                )
            except ValueError:
                pass  # duplicata esperada
            except Exception as e:
                with lock:
                    erros.append(e)

        threads = [
            threading.Thread(target=registrar, args=(i,))
            for i in range(20)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(erros), 0)
        self.assertGreaterEqual(self.manager._scheduler.count, 1)

    # ── parada segura ───────────────────────────────────────────────

    def test_parada_segura_libera_recursos(self) -> None:
        """stop_all libera recursos corretamente."""
        self.manager.register_product(
            "p1", "https://example.com/p1", "Amazon",
        )
        self.manager.start_all()
        self.manager.stop_all(wait=True)

        # Após parar, deve ser possível reiniciar
        self.manager.start_all()
        self.assertTrue(self.manager.is_running)
        self.manager.stop_all()

    def test_parada_segura_com_wait_false(self) -> None:
        """stop_all com wait=False não bloqueia."""
        self.manager.start_all()
        self.manager.stop_all(wait=False)
        # Não deve levantar exceção
        self.assertFalse(self.manager.is_running)

    # ── execução duplicada ──────────────────────────────────────────

    def test_evitar_execucao_duplicada(self) -> None:
        """start_all não duplica execução se já estiver rodando."""
        self.manager.start_all()
        thread_atual = threading.active_count()
        self.manager.start_all()  # no-op
        # Nenhuma thread extra deve ser criada
        self.assertLessEqual(threading.active_count(), thread_atual + 1)
        self.manager.stop_all()

    # ── exceções isoladas ───────────────────────────────────────────

    def test_excecao_em_um_monitor_nao_interrompe_outros(self) -> None:
        """Exceção em um monitor não interrompe os demais."""
        callback_falha = Mock(side_effect=RuntimeError("Erro simulado"))
        self.manager.set_on_due_callback(callback_falha)

        self.manager.register_product(
            "p1", "https://example.com/p1", "Amazon",
            interval_minutes=1,
        )
        watcher = self.manager.get_product("p1")
        watcher.last_check = datetime.now() - timedelta(minutes=10)

        # start_all não deve propagar exceção
        self.manager.start_all()
        time.sleep(0.3)
        self.manager.stop_all()

        # O callback deve ter sido chamado (erro é logado, não propagado)
        self.assertGreaterEqual(callback_falha.call_count, 1)

    def test_excecao_no_start_watcher_manager_nao_interrompe(self) -> None:
        """Exceção ao iniciar ProductWatcherManager não interrompe start_all."""
        with patch.object(
            self.manager._watcher_manager, "start",
            side_effect=RuntimeError("Falha simulada"),
        ):
            self.manager.start_all()  # não deve propagar exceção

        # MonitorManager deve ter iniciado mesmo com falha no watcher
        self.assertTrue(self.manager.is_running)
        self.manager.stop_all()

    # ── logs de execução ────────────────────────────────────────────

    def test_logs_de_inicio_e_parada(self) -> None:
        """start_all e stop_all geram logs informativos."""
        with patch.object(logging.getLogger("src.monitor.monitor_manager"), "info") as mock_log:
            self.manager.start_all()
            self.manager.stop_all()

            # Deve ter logado início e parada
            mensagens = [args[0] for args, _ in mock_log.call_args_list]
            mensagem_unida = " ".join(str(m) for m in mensagens)
            self.assertIn("Iniciando todos os monitores", mensagem_unida)
            self.assertIn("Parando todos os monitores", mensagem_unida)

    def test_logs_de_registro_de_produto(self) -> None:
        """Registro de produto gera log informativo."""
        with patch.object(logging.getLogger("src.monitor.monitor_manager"), "info") as mock_log:
            self.manager.register_product(
                "p1", "https://example.com/p1", "Amazon",
                label="SSD 1TB",
            )
            # Verifica se alguma chamada de log contém a mensagem esperada
            encontrou = False
            for args, _ in mock_log.call_args_list:
                if args and "Produto registrado" in str(args[0]):
                    encontrou = True
                    break
            self.assertTrue(encontrou)

    # ── estatísticas integradas ─────────────────────────────────────

    def test_stats_apos_start_all(self) -> None:
        """Stats reflete estado após start_all."""
        self.manager.register_product(
            "p1", "https://example.com/p1", "Amazon",
        )
        self.manager.start_all()
        stats = self.manager.stats()
        self.assertTrue(stats.running)
        self.assertEqual(stats.total_watchers, 1)
        self.manager.stop_all()

    def test_stats_apos_stop_all(self) -> None:
        """Stats reflete estado após stop_all."""
        self.manager.register_product(
            "p1", "https://example.com/p1", "Amazon",
        )
        self.manager.start_all()
        self.manager.stop_all()
        stats = self.manager.stats()
        self.assertFalse(stats.running)

    # ── cenários de borda ───────────────────────────────────────────

    def test_start_all_sem_produtos(self) -> None:
        """start_all sem produtos registrados não gera erro."""
        self.manager.start_all()
        self.assertTrue(self.manager.is_running)
        self.manager.stop_all()

    def test_stop_all_com_watcher_em_erro(self) -> None:
        """stop_all com watcher em estado de erro."""
        self.manager.register_product(
            "p1", "https://example.com/p1", "Amazon",
        )
        watcher = self.manager.get_product("p1")
        watcher.mark_error()
        self.manager.start_all()
        self.manager.stop_all()
        self.assertFalse(self.manager.is_running)

    def test_ciclo_completo_com_multiplos_produtos(self) -> None:
        """Ciclo completo com múltiplos produtos."""
        callback = Mock()
        self.manager.set_on_due_callback(callback)

        for i in range(5):
            self.manager.register_product(
                f"p{i}", f"https://example.com/p{i}", "Amazon",
                interval_minutes=1,
            )
            watcher = self.manager.get_product(f"p{i}")
            watcher.last_check = datetime.now() - timedelta(minutes=10)

        self.manager.start_all()
        time.sleep(0.3)
        self.manager.stop_all()

        # Callback deve ter sido chamado para produtos devidos
        self.assertGreaterEqual(callback.call_count, 1)

    def test_limpeza_de_recursos_apos_stop_all(self) -> None:
        """Recursos são limpos após stop_all."""
        self.manager.register_product(
            "p1", "https://example.com/p1", "Amazon",
        )
        self.manager.start_all()
        self.manager.stop_all(wait=True)

        # Deve ser possível registrar novos produtos após parar
        watcher = self.manager.register_product(
            "p2", "https://example.com/p2", "Mercado Livre",
        )
        self.assertIsNotNone(watcher)
        self.assertEqual(watcher.product_id, "p2")

    def test_unregister_product_remove_de_ambos(self) -> None:
        """unregister_product remove do scheduler e do watcher manager."""
        self.manager.register_product(
            "p1", "https://example.com/p1", "Amazon",
        )
        self.assertIsNotNone(self.manager.get_product("p1"))
        self.assertIsNotNone(self.manager._watcher_manager.get("p1"))

        self.manager.unregister_product("p1")

        self.assertIsNone(self.manager.get_product("p1"))
        self.assertIsNone(self.manager._watcher_manager.get("p1"))


if __name__ == "__main__":
    unittest.main()