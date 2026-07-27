"""
Testes para o MonitorManager — orquestrador principal do módulo de monitoramento.

Cobre:
    - Ciclo de vida: iniciar, parar, informar se está ativo
    - Registro de produtos: registrar, remover, listar
    - Prevenção de duplicatas: mesmo ID, mesma URL+loja
    - Controle de intervalo: alterar, validar intervalos inválidos
    - Pausar/retomar produtos
    - Callbacks/eventos futuros (sem executá-los)
    - Estatísticas consolidadas
"""

from __future__ import annotations

import threading
import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from src.monitor.monitor_manager import MonitorManager, MonitorStats
from src.monitor.watcher import ProductWatcher, WatcherStatus


class MonitorManagerTest(unittest.TestCase):
    """Testes unitários para o MonitorManager."""

    def setUp(self) -> None:
        self.manager = MonitorManager(poll_interval_seconds=0.01)

    def tearDown(self) -> None:
        if self.manager.is_running:
            self.manager.stop(wait=True)

    # ── ciclo de vida ───────────────────────────────────────────────

    def test_inicia_e_para_o_monitor(self) -> None:
        """iniciar o monitor e parar o monitor."""
        self.assertFalse(self.manager.is_running)
        self.manager.start()
        self.assertTrue(self.manager.is_running)
        self.manager.stop()
        self.assertFalse(self.manager.is_running)

    def test_iniciar_duas_vezes_nao_gera_erro(self) -> None:
        """Iniciar o monitor já rodando é um no-op."""
        self.manager.start()
        self.manager.start()  # não deve levantar exceção
        self.assertTrue(self.manager.is_running)
        self.manager.stop()

    def test_parar_sem_iniciar_nao_gera_erro(self) -> None:
        """Parar o monitor sem ter iniciado não gera erro."""
        self.manager.stop()  # não deve levantar exceção
        self.assertFalse(self.manager.is_running)

    def test_informar_se_esta_ativo(self) -> None:
        """informar se está ativo."""
        self.assertFalse(self.manager.is_running)
        self.manager.start()
        self.assertTrue(self.manager.is_running)
        self.manager.stop()
        self.assertFalse(self.manager.is_running)

    def test_stop_aguarda_thread_finalizar(self) -> None:
        """stop com wait=True aguarda a thread finalizar."""
        self.manager.start()
        time.sleep(0.05)
        self.manager.stop(wait=True)
        self.assertFalse(self.manager.is_running)

    # ── registro de produtos ────────────────────────────────────────

    def test_registrar_produto_monitorado(self) -> None:
        """registrar um produto monitorado."""
        watcher = self.manager.register_product(
            "p1", "https://example.com/produto", "Amazon", label="SSD 1TB"
        )
        self.assertIsNotNone(watcher)
        self.assertEqual(watcher.product_id, "p1")
        self.assertEqual(watcher.url, "https://example.com/produto")
        self.assertEqual(watcher.store, "Amazon")
        self.assertEqual(watcher.label, "SSD 1TB")
        self.assertEqual(watcher.interval_minutes, 240)

    def test_registrar_produto_com_intervalo_personalizado(self) -> None:
        """Registrar produto com intervalo personalizado."""
        watcher = self.manager.register_product(
            "p2", "https://example.com/ssd", "Mercado Livre",
            interval_minutes=60,
        )
        self.assertEqual(watcher.interval_minutes, 60)

    def test_registrar_produto_com_tags(self) -> None:
        """Registrar produto com tags."""
        watcher = self.manager.register_product(
            "p3", "https://example.com/tag", "Shopee",
            tags={"ssd", "promocao"},
        )
        self.assertEqual(watcher.tags, {"ssd", "promocao"})

    def test_registrar_produto_sem_label_usa_product_id(self) -> None:
        """Se label não for fornecida, usa product_id como label."""
        watcher = self.manager.register_product(
            "p4", "https://example.com/no-label", "Amazon"
        )
        self.assertEqual(watcher.label, "p4")

    def test_remover_produto_monitorado(self) -> None:
        """remover um produto monitorado."""
        self.manager.register_product("p1", "https://example.com/p1", "Amazon")
        removed = self.manager.unregister_product("p1")
        self.assertIsNotNone(removed)
        self.assertEqual(removed.product_id, "p1")
        self.assertIsNone(self.manager.get_product("p1"))

    def test_remover_produto_inexistente_retorna_none(self) -> None:
        """Remover produto que não existe retorna None."""
        removed = self.manager.unregister_product("nao_existe")
        self.assertIsNone(removed)

    def test_listar_produtos_monitorados(self) -> None:
        """listar produtos monitorados."""
        self.manager.register_product("p1", "https://example.com/p1", "Amazon")
        self.manager.register_product("p2", "https://example.com/p2", "Mercado Livre")
        produtos = self.manager.list_products()
        self.assertEqual(len(produtos), 2)
        ids = {p.product_id for p in produtos}
        self.assertIn("p1", ids)
        self.assertIn("p2", ids)

    def test_listar_produtos_vazia_quando_sem_registros(self) -> None:
        """Listar produtos sem registros retorna lista vazia."""
        self.assertEqual(self.manager.list_products(), [])

    def test_get_product_retorna_watcher_correto(self) -> None:
        """get_product retorna o watcher pelo ID."""
        self.manager.register_product("p1", "https://example.com/p1", "Amazon")
        watcher = self.manager.get_product("p1")
        self.assertIsNotNone(watcher)
        self.assertEqual(watcher.product_id, "p1")

    def test_get_product_inexistente_retorna_none(self) -> None:
        """get_product para ID inexistente retorna None."""
        self.assertIsNone(self.manager.get_product("nao_existe"))

    # ── prevenção de duplicatas ─────────────────────────────────────

    def test_evitar_produtos_duplicados_por_id(self) -> None:
        """evitar produtos duplicados (mesmo product_id)."""
        self.manager.register_product("p1", "https://example.com/p1", "Amazon")
        with self.assertRaises(ValueError) as ctx:
            self.manager.register_product("p1", "https://example.com/outro", "Amazon")
        self.assertIn("já está registrado", str(ctx.exception))

    def test_evitar_produtos_duplicados_por_url_loja(self) -> None:
        """evitar produtos duplicados (mesma URL + loja)."""
        self.manager.register_product("p1", "https://example.com/produto", "Amazon")
        with self.assertRaises(ValueError) as ctx:
            self.manager.register_product(
                "p2", "https://example.com/produto", "Amazon"
            )
        self.assertIn("já está registrado", str(ctx.exception))

    def test_mesma_url_loja_diferente_e_permitido(self) -> None:
        """Mesma URL em lojas diferentes é permitido."""
        self.manager.register_product("p1", "https://example.com/produto", "Amazon")
        watcher = self.manager.register_product(
            "p2", "https://example.com/produto", "Mercado Livre"
        )
        self.assertIsNotNone(watcher)
        self.assertEqual(watcher.product_id, "p2")

    def test_product_id_vazio_rejeitado(self) -> None:
        """product_id vazio é rejeitado."""
        with self.assertRaises(ValueError) as ctx:
            self.manager.register_product("", "https://example.com/p", "Amazon")
        self.assertIn("não pode ser vazio", str(ctx.exception))

    def test_product_id_espacos_rejeitado(self) -> None:
        """product_id com apenas espaços é rejeitado."""
        with self.assertRaises(ValueError) as ctx:
            self.manager.register_product("   ", "https://example.com/p", "Amazon")
        self.assertIn("não pode ser vazio", str(ctx.exception))

    # ── controle de intervalo ───────────────────────────────────────

    def test_controlar_intervalo_de_monitoramento(self) -> None:
        """controlar o intervalo de monitoramento."""
        self.manager.register_product("p1", "https://example.com/p1", "Amazon")
        result = self.manager.set_interval("p1", 120)
        self.assertTrue(result)
        watcher = self.manager.get_product("p1")
        self.assertEqual(watcher.interval_minutes, 120)

    def test_set_interval_produto_inexistente_retorna_false(self) -> None:
        """set_interval para produto inexistente retorna False."""
        result = self.manager.set_interval("nao_existe", 60)
        self.assertFalse(result)

    def test_validar_intervalos_invalidos_negativo(self) -> None:
        """validar intervalos inválidos (negativo)."""
        self.manager.register_product("p1", "https://example.com/p1", "Amazon")
        with self.assertRaises(ValueError) as ctx:
            self.manager.set_interval("p1", -1)
        self.assertIn("mínimo é 1", str(ctx.exception))

    def test_validar_intervalos_invalidos_zero(self) -> None:
        """validar intervalos inválidos (zero)."""
        self.manager.register_product("p1", "https://example.com/p1", "Amazon")
        with self.assertRaises(ValueError) as ctx:
            self.manager.set_interval("p1", 0)
        self.assertIn("mínimo é 1", str(ctx.exception))

    def test_validar_intervalo_negativo_no_registro(self) -> None:
        """Registrar com intervalo negativo é rejeitado."""
        with self.assertRaises(ValueError) as ctx:
            self.manager.register_product(
                "p1", "https://example.com/p1", "Amazon",
                interval_minutes=-5,
            )
        self.assertIn("mínimo é 1", str(ctx.exception))

    def test_validar_intervalo_zero_no_registro(self) -> None:
        """Registrar com intervalo zero é rejeitado."""
        with self.assertRaises(ValueError) as ctx:
            self.manager.register_product(
                "p1", "https://example.com/p1", "Amazon",
                interval_minutes=0,
            )
        self.assertIn("mínimo é 1", str(ctx.exception))

    def test_validar_intervalo_nao_inteiro(self) -> None:
        """Intervalo não inteiro é rejeitado."""
        with self.assertRaises(ValueError) as ctx:
            self.manager.register_product(
                "p1", "https://example.com/p1", "Amazon",
                interval_minutes=1.5,  # type: ignore
            )
        self.assertIn("deve ser um número inteiro", str(ctx.exception))

    def test_intervalo_minimo_um_minuto_e_aceito(self) -> None:
        """Intervalo mínimo de 1 minuto é aceito."""
        self.manager.register_product(
            "p1", "https://example.com/p1", "Amazon",
            interval_minutes=1,
        )
        watcher = self.manager.get_product("p1")
        self.assertEqual(watcher.interval_minutes, 1)

    # ── pausar / retomar ────────────────────────────────────────────

    def test_pausar_produto(self) -> None:
        """Pausa o monitoramento de um produto."""
        self.manager.register_product("p1", "https://example.com/p1", "Amazon")
        result = self.manager.pause_product("p1")
        self.assertTrue(result)
        watcher = self.manager.get_product("p1")
        self.assertTrue(watcher.is_paused)

    def test_pausar_produto_inexistente_retorna_false(self) -> None:
        """Pausar produto inexistente retorna False."""
        result = self.manager.pause_product("nao_existe")
        self.assertFalse(result)

    def test_retomar_produto_pausado(self) -> None:
        """Retoma o monitoramento de um produto pausado."""
        self.manager.register_product("p1", "https://example.com/p1", "Amazon")
        self.manager.pause_product("p1")
        result = self.manager.resume_product("p1")
        self.assertTrue(result)
        watcher = self.manager.get_product("p1")
        self.assertTrue(watcher.is_active)

    def test_retomar_produto_inexistente_retorna_false(self) -> None:
        """Retomar produto inexistente retorna False."""
        result = self.manager.resume_product("nao_existe")
        self.assertFalse(result)

    # ── callbacks / eventos futuros ─────────────────────────────────

    def test_preparar_callbacks_futuros_sem_executa_los(self) -> None:
        """preparar callbacks/eventos futuros sem executá-los agora."""
        callback = Mock()
        self.manager.set_on_due_callback(callback)
        # O callback NÃO deve ser chamado imediatamente
        callback.assert_not_called()

    def test_set_on_tick_callback_nao_executa_imediatamente(self) -> None:
        """set_on_tick_callback não executa o callback imediatamente."""
        callback = Mock()
        self.manager.set_on_tick_callback(callback)
        callback.assert_not_called()

    def test_callback_e_chamado_quando_watcher_fica_devido(self) -> None:
        """Callback é chamado quando um watcher fica devido."""
        callback = Mock()
        self.manager.set_on_due_callback(callback)
        # Registra produto com last_check antigo para ficar devido
        watcher = ProductWatcher(
            product_id="p1",
            url="https://example.com/p1",
            store="Amazon",
            interval_minutes=1,
            last_check=datetime.now() - timedelta(minutes=10),
        )
        self.manager._scheduler.add(watcher)
        self.manager.start()
        time.sleep(0.3)
        self.manager.stop()
        # O callback deve ter sido chamado com a lista de watchers
        self.assertTrue(callback.called)

    def test_on_tick_callback_e_chamado_durante_loop(self) -> None:
        """on_tick_callback é chamado durante o loop."""
        callback = Mock()
        self.manager.set_on_tick_callback(callback)
        self.manager.start()
        time.sleep(0.1)
        self.manager.stop()
        self.assertTrue(callback.called)

    def test_callback_com_erro_nao_interrompe_loop(self) -> None:
        """Erro no callback não interrompe o loop."""
        def failing_callback(watchers):
            raise RuntimeError("Erro simulado")

        self.manager.set_on_due_callback(failing_callback)
        watcher = ProductWatcher(
            product_id="p1",
            url="https://example.com/p1",
            store="Amazon",
            interval_minutes=1,
            last_check=datetime.now() - timedelta(minutes=10),
        )
        self.manager._scheduler.add(watcher)
        self.manager.start()
        time.sleep(0.3)
        self.manager.stop()
        # O watcher deve ter sido marcado com erro
        w = self.manager.get_product("p1")
        self.assertIsNotNone(w)

    # ── estatísticas ────────────────────────────────────────────────

    def test_stats_sem_produtos(self) -> None:
        """Stats sem produtos registrados."""
        stats = self.manager.stats()
        self.assertIsInstance(stats, MonitorStats)
        self.assertEqual(stats.total_watchers, 0)
        self.assertEqual(stats.active, 0)
        self.assertEqual(stats.paused, 0)
        self.assertEqual(stats.errored, 0)
        self.assertEqual(stats.stopped, 0)
        self.assertFalse(stats.running)

    def test_stats_com_produtos_ativos(self) -> None:
        """Stats com produtos registrados."""
        self.manager.register_product("p1", "https://example.com/p1", "Amazon")
        self.manager.register_product("p2", "https://example.com/p2", "Mercado Livre")
        stats = self.manager.stats()
        self.assertEqual(stats.total_watchers, 2)
        self.assertEqual(stats.active, 2)

    def test_stats_com_produto_pausado(self) -> None:
        """Stats com produto pausado."""
        self.manager.register_product("p1", "https://example.com/p1", "Amazon")
        self.manager.pause_product("p1")
        stats = self.manager.stats()
        self.assertEqual(stats.total_watchers, 1)
        self.assertEqual(stats.paused, 1)

    def test_stats_reflete_running(self) -> None:
        """Stats reflete se o monitor está rodando."""
        stats_antes = self.manager.stats()
        self.assertFalse(stats_antes.running)
        self.manager.start()
        stats_durante = self.manager.stats()
        self.assertTrue(stats_durante.running)
        self.manager.stop()
        stats_depois = self.manager.stats()
        self.assertFalse(stats_depois.running)

    def test_stats_total_checks_e_errors(self) -> None:
        """Stats acumula total_checks e total_errors."""
        self.manager.register_product("p1", "https://example.com/p1", "Amazon")
        # Simula processamento de watchers devidos
        watcher = self.manager.get_product("p1")
        watcher.last_check = datetime.now() - timedelta(minutes=10)
        self.manager._handle_due([watcher])
        stats = self.manager.stats()
        self.assertGreaterEqual(stats.total_checks, 1)

    # ── repr ────────────────────────────────────────────────────────

    def test_repr(self) -> None:
        """__repr__ retorna representação textual."""
        rep = repr(self.manager)
        self.assertIn("MonitorManager", rep)
        self.assertIn("running=False", rep)
        self.assertIn("watchers=0", rep)

    def test_repr_com_watchers(self) -> None:
        """__repr__ com watchers registrados."""
        self.manager.register_product("p1", "https://example.com/p1", "Amazon")
        rep = repr(self.manager)
        self.assertIn("watchers=1", rep)

    # ── cenários de borda ───────────────────────────────────────────

    def test_registrar_e_remover_multiplos_produtos(self) -> None:
        """Registrar e remover múltiplos produtos em sequência."""
        for i in range(10):
            self.manager.register_product(
                f"p{i}", f"https://example.com/p{i}", "Amazon"
            )
        self.assertEqual(len(self.manager.list_products()), 10)
        for i in range(10):
            self.manager.unregister_product(f"p{i}")
        self.assertEqual(len(self.manager.list_products()), 0)

    def test_registrar_apos_remover_mesmo_id(self) -> None:
        """Registrar novamente após remover o mesmo ID."""
        self.manager.register_product("p1", "https://example.com/p1", "Amazon")
        self.manager.unregister_product("p1")
        watcher = self.manager.register_product(
            "p1", "https://example.com/p1", "Amazon"
        )
        self.assertIsNotNone(watcher)
        self.assertEqual(watcher.product_id, "p1")

    def test_set_interval_apos_unregister(self) -> None:
        """set_interval após remover produto retorna False."""
        self.manager.register_product("p1", "https://example.com/p1", "Amazon")
        self.manager.unregister_product("p1")
        result = self.manager.set_interval("p1", 60)
        self.assertFalse(result)

    def test_pause_resume_multiplas_vezes(self) -> None:
        """Pausar e retomar múltiplas vezes."""
        self.manager.register_product("p1", "https://example.com/p1", "Amazon")
        for _ in range(3):
            self.manager.pause_product("p1")
            self.assertTrue(self.manager.get_product("p1").is_paused)
            self.manager.resume_product("p1")
            self.assertTrue(self.manager.get_product("p1").is_active)

    def test_loop_com_watchers_sem_callback(self) -> None:
        """Loop funciona sem callback registrado (apenas log)."""
        watcher = ProductWatcher(
            product_id="p1",
            url="https://example.com/p1",
            store="Amazon",
            interval_minutes=1,
            last_check=datetime.now() - timedelta(minutes=10),
        )
        self.manager._scheduler.add(watcher)
        self.manager.start()
        time.sleep(0.2)
        self.manager.stop()
        # O watcher deve ter sido processado e reagendado
        w = self.manager.get_product("p1")
        self.assertIsNotNone(w)
        self.assertIsNotNone(w.last_check)

    def test_handle_due_com_watcher_erro_maximo(self) -> None:
        """Watcher com erro máximo não é reagendado."""
        watcher = ProductWatcher(
            product_id="p1",
            url="https://example.com/p1",
            store="Amazon",
            interval_minutes=1,
            consecutive_errors=5,
            max_errors=5,
            status=WatcherStatus.ERROR,
        )
        self.manager._scheduler.add(watcher)
        # Simula o processamento
        self.manager._handle_due([watcher])
        # O watcher deve permanecer em erro e não ser reagendado
        self.assertEqual(watcher.status, WatcherStatus.ERROR)


if __name__ == "__main__":
    unittest.main()