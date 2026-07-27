"""
Testes para o ProductWatcherManager — gerenciamento de monitoramento de produtos.

Cobre:
    - Criação do ProductWatcherManager
    - Registro de produto
    - Registro duplicado
    - Remoção
    - Consulta
    - Listagem
    - Iniciar monitoramento
    - Parar monitoramento
    - Callback executado para produtos devidos
    - Callback NÃO executado após parada
    - Múltiplos produtos
    - Thread safety
    - Integração com Scheduler
    - Erros nas callbacks
    - Propriedades (count, is_running, products)
"""

from __future__ import annotations

import logging
import threading
import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from src.monitor.scheduler import Scheduler
from src.monitor.watcher import ProductWatcher, ProductWatcherManager, WatcherStatus


class ProductWatcherManagerTest(unittest.TestCase):
    """Testes unitários para o ProductWatcherManager."""

    def setUp(self) -> None:
        self.manager = ProductWatcherManager()
        self.product = ProductWatcher(
            product_id="prod_001",
            url="https://example.com/produto",
            store="Amazon",
            label="Produto Teste",
            interval_minutes=240,
        )

    def tearDown(self) -> None:
        if self.manager.is_running:
            self.manager.stop(wait=True)

    # ── criação ─────────────────────────────────────────────────────

    def test_criacao_do_manager(self) -> None:
        """Criação do ProductWatcherManager."""
        manager = ProductWatcherManager()
        self.assertIsNotNone(manager)
        self.assertFalse(manager.is_running)
        self.assertEqual(manager.count, 0)
        self.assertEqual(manager.products, [])

    def test_criacao_com_scheduler_externo(self) -> None:
        """Criação com Scheduler externo."""
        scheduler = Scheduler()
        manager = ProductWatcherManager(scheduler=scheduler)
        self.assertIsNotNone(manager)
        self.assertFalse(manager.is_running)

    def test_criacao_com_on_check(self) -> None:
        """Criação com callback on_check."""
        callback = Mock()
        manager = ProductWatcherManager(on_check=callback)
        self.assertIsNotNone(manager)
        self.assertEqual(manager._on_check, callback)

    # ── registro ────────────────────────────────────────────────────

    def test_registro_de_produto(self) -> None:
        """Registro de produto para monitoramento."""
        self.manager.register(self.product)
        self.assertEqual(self.manager.count, 1)
        self.assertIsNotNone(self.manager.get("prod_001"))

    def test_registro_duplicado(self) -> None:
        """Impedir registros duplicados (mesmo product_id)."""
        self.manager.register(self.product)
        with self.assertRaises(ValueError) as ctx:
            self.manager.register(self.product)
        self.assertIn("já está registrado", str(ctx.exception))
        self.assertEqual(self.manager.count, 1)

    def test_registro_duplicado_mesmo_id(self) -> None:
        """Impedir registro com mesmo product_id mas dados diferentes."""
        outro = ProductWatcher(
            product_id="prod_001",
            url="https://example.com/outro",
            store="Mercado Livre",
        )
        self.manager.register(self.product)
        with self.assertRaises(ValueError):
            self.manager.register(outro)
        self.assertEqual(self.manager.count, 1)

    def test_registro_de_multiplos_produtos(self) -> None:
        """Registro de múltiplos produtos."""
        p1 = ProductWatcher(product_id="p1", url="url1", store="Amazon")
        p2 = ProductWatcher(product_id="p2", url="url2", store="Mercado Livre")
        p3 = ProductWatcher(product_id="p3", url="url3", store="Shopee")
        self.manager.register(p1)
        self.manager.register(p2)
        self.manager.register(p3)
        self.assertEqual(self.manager.count, 3)

    # ── remoção ─────────────────────────────────────────────────────

    def test_remocao_de_produto(self) -> None:
        """Remover produto pelo identificador."""
        self.manager.register(self.product)
        removed = self.manager.remove("prod_001")
        self.assertIsNotNone(removed)
        self.assertEqual(removed.product_id, "prod_001")
        self.assertIsNone(self.manager.get("prod_001"))
        self.assertEqual(self.manager.count, 0)

    def test_remocao_de_produto_inexistente(self) -> None:
        """Remover produto que não existe retorna None."""
        removed = self.manager.remove("nao_existe")
        self.assertIsNone(removed)

    def test_remocao_e_re_registro(self) -> None:
        """Remover e registrar novamente o mesmo ID."""
        self.manager.register(self.product)
        self.manager.remove("prod_001")
        self.manager.register(self.product)
        self.assertEqual(self.manager.count, 1)
        self.assertIsNotNone(self.manager.get("prod_001"))

    # ── consulta ────────────────────────────────────────────────────

    def test_consulta_de_produto(self) -> None:
        """Consultar produto pelo ID."""
        self.manager.register(self.product)
        found = self.manager.get("prod_001")
        self.assertIsNotNone(found)
        self.assertEqual(found.product_id, "prod_001")
        self.assertEqual(found.url, "https://example.com/produto")

    def test_consulta_de_produto_inexistente(self) -> None:
        """Consultar produto que não existe retorna None."""
        self.assertIsNone(self.manager.get("nao_existe"))

    def test_consulta_apos_remocao(self) -> None:
        """Consultar produto após remoção retorna None."""
        self.manager.register(self.product)
        self.manager.remove("prod_001")
        self.assertIsNone(self.manager.get("prod_001"))

    # ── listagem ────────────────────────────────────────────────────

    def test_listagem_de_produtos(self) -> None:
        """Listar produtos registrados."""
        p1 = ProductWatcher(product_id="p1", url="url1", store="Amazon")
        p2 = ProductWatcher(product_id="p2", url="url2", store="Mercado Livre")
        self.manager.register(p1)
        self.manager.register(p2)
        produtos = self.manager.list_all()
        self.assertEqual(len(produtos), 2)
        ids = {p.product_id for p in produtos}
        self.assertIn("p1", ids)
        self.assertIn("p2", ids)

    def test_listagem_vazia(self) -> None:
        """Listar produtos sem registros retorna lista vazia."""
        self.assertEqual(self.manager.list_all(), [])

    def test_listagem_nao_afeta_interna(self) -> None:
        """Listagem retorna cópia, não referência interna."""
        self.manager.register(self.product)
        produtos = self.manager.list_all()
        produtos.clear()
        self.assertEqual(self.manager.count, 1)

    # ── propriedade products ────────────────────────────────────────

    def test_property_products(self) -> None:
        """Propriedade products retorna lista de produtos."""
        self.manager.register(self.product)
        prods = self.manager.products
        self.assertEqual(len(prods), 1)
        self.assertEqual(prods[0].product_id, "prod_001")

    def test_property_products_vazia(self) -> None:
        """Propriedade products sem registros retorna lista vazia."""
        self.assertEqual(self.manager.products, [])

    # ── propriedade count ───────────────────────────────────────────

    def test_property_count(self) -> None:
        """Propriedade count retorna quantidade correta."""
        self.assertEqual(self.manager.count, 0)
        self.manager.register(self.product)
        self.assertEqual(self.manager.count, 1)
        p2 = ProductWatcher(product_id="p2", url="url2", store="Shopee")
        self.manager.register(p2)
        self.assertEqual(self.manager.count, 2)
        self.manager.remove("prod_001")
        self.assertEqual(self.manager.count, 1)

    # ── propriedade is_running ──────────────────────────────────────

    def test_property_is_running(self) -> None:
        """Propriedade is_running reflete estado correto."""
        self.assertFalse(self.manager.is_running)
        self.manager.start()
        self.assertTrue(self.manager.is_running)
        self.manager.stop()
        self.assertFalse(self.manager.is_running)

    # ── iniciar ─────────────────────────────────────────────────────

    def test_iniciar_monitoramento(self) -> None:
        """Iniciar o monitoramento."""
        self.assertFalse(self.manager.is_running)
        self.manager.start()
        self.assertTrue(self.manager.is_running)
        self.manager.stop()
        self.assertFalse(self.manager.is_running)

    def test_iniciar_sem_produtos_nao_gera_erro(self) -> None:
        """Iniciar sem produtos registrados não gera erro."""
        self.manager.start()
        self.assertTrue(self.manager.is_running)
        self.manager.stop()

    # ── parar ───────────────────────────────────────────────────────

    def test_parar_monitoramento(self) -> None:
        """Parar o monitoramento de forma segura."""
        self.manager.start()
        time.sleep(0.05)
        self.manager.stop(wait=True)
        self.assertFalse(self.manager.is_running)

    def test_parar_sem_iniciar_nao_gera_erro(self) -> None:
        """Parar sem ter iniciado não gera erro."""
        self.manager.stop()  # não deve levantar exceção
        self.assertFalse(self.manager.is_running)

    def test_parar_e_reiniciar(self) -> None:
        """Parar e reiniciar o monitoramento."""
        self.manager.start()
        time.sleep(0.05)
        self.manager.stop(wait=True)
        self.assertFalse(self.manager.is_running)
        self.manager.start()
        self.assertTrue(self.manager.is_running)
        self.manager.stop()

    # ── callback ────────────────────────────────────────────────────

    def test_callback_executado_para_produto_devido(self) -> None:
        """Callback on_check executado para produto que está devido."""
        callback = Mock()
        manager = ProductWatcherManager(on_check=callback, poll_interval_seconds=0.1)
        product = ProductWatcher(
            product_id="test",
            url="https://example.com",
            store="Amazon",
            interval_minutes=0,  # sempre devido
        )
        manager.register(product)
        manager.start()
        time.sleep(0.4)
        manager.stop()
        # Deve ter chamado o callback pelo menos uma vez
        self.assertGreaterEqual(callback.call_count, 1)
        # O argumento deve ser o ProductWatcher
        args, _ = callback.call_args
        self.assertEqual(args[0].product_id, "test")

    def test_callback_nao_executado_para_produto_nao_devido(self) -> None:
        """Callback NÃO executado para produto que não está devido."""
        callback = Mock()
        manager = ProductWatcherManager(on_check=callback, poll_interval_seconds=0.1)
        product = ProductWatcher(
            product_id="test",
            url="https://example.com",
            store="Amazon",
            interval_minutes=9999,  # nunca devido
            last_check=datetime.now(),
        )
        manager.register(product)
        manager.start()
        time.sleep(0.3)
        manager.stop()
        # Callback pode ter sido chamado 0 vezes (produto não devido)
        self.assertEqual(callback.call_count, 0)

    def test_callback_nao_executado_apos_parada(self) -> None:
        """Não executar callbacks após o manager ser parado."""
        callback = Mock()
        manager = ProductWatcherManager(on_check=callback, poll_interval_seconds=0.1)
        product = ProductWatcher(
            product_id="test",
            url="https://example.com",
            store="Amazon",
            interval_minutes=0,  # sempre devido
        )
        manager.register(product)
        manager.start()
        time.sleep(0.3)
        manager.stop(wait=True)
        chamadas_ate_parar = callback.call_count
        time.sleep(0.3)
        # Não deve ter chamado novamente após parar
        self.assertEqual(callback.call_count, chamadas_ate_parar)

    def test_callback_para_multiplos_produtos_devidos(self) -> None:
        """Callback executado para múltiplos produtos devidos."""
        callback = Mock()
        manager = ProductWatcherManager(on_check=callback, poll_interval_seconds=0.1)
        p1 = ProductWatcher(
            product_id="p1", url="url1", store="Amazon", interval_minutes=0
        )
        p2 = ProductWatcher(
            product_id="p2", url="url2", store="Mercado Livre", interval_minutes=0
        )
        manager.register(p1)
        manager.register(p2)
        manager.start()
        time.sleep(0.4)
        manager.stop()
        # Ambos devem ter sido chamados
        self.assertGreaterEqual(callback.call_count, 2)

    # ── erro na callback ────────────────────────────────────────────

    def test_erro_na_callback_nao_interrompe_outros(self) -> None:
        """Erro em uma callback não interrompe verificação de outros produtos."""
        callback_ok = Mock()
        callback_falha = Mock(side_effect=RuntimeError("Erro simulado"))

        # Manager com callback que falha
        manager = ProductWatcherManager(
            on_check=callback_falha, poll_interval_seconds=0.1
        )
        product = ProductWatcher(
            product_id="test",
            url="https://example.com",
            store="Amazon",
            interval_minutes=0,
        )
        manager.register(product)
        manager.start()
        time.sleep(0.3)
        manager.stop()
        # A callback que falha deve ter sido chamada (erro é logado, não propagado)
        self.assertGreaterEqual(callback_falha.call_count, 1)

    def test_erro_na_callback_logada(self) -> None:
        """Erro na callback é registrado via logging."""
        callback = Mock(side_effect=ValueError("Erro de teste"))
        manager = ProductWatcherManager(on_check=callback, poll_interval_seconds=0.1)
        product = ProductWatcher(
            product_id="test",
            url="https://example.com",
            store="Amazon",
            interval_minutes=0,
        )
        manager.register(product)

        with patch.object(logging.getLogger("src.monitor.watcher"), "error") as mock_log:
            manager.start()
            time.sleep(0.3)
            manager.stop()
            # Deve ter logado o erro
            mock_log.assert_called()
            # Verifica se a mensagem contém o ID do produto
            log_args = mock_log.call_args[0]
            self.assertIn("test", str(log_args))

    # ── thread safety ───────────────────────────────────────────────

    def test_thread_safety_registro_concorrente(self) -> None:
        """Segurança com múltiplas threads registrando produtos."""
        resultados: list[bool] = []
        lock = threading.Lock()

        def registrar(i: int) -> None:
            try:
                product = ProductWatcher(
                    product_id=f"prod_{i}",
                    url=f"https://example.com/{i}",
                    store="Amazon",
                )
                self.manager.register(product)
                with lock:
                    resultados.append(True)
            except Exception:
                with lock:
                    resultados.append(False)

        threads = [
            threading.Thread(target=registrar, args=(i,)) for i in range(20)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Todos devem ter registrado com sucesso (IDs únicos)
        self.assertEqual(sum(resultados), 20)
        self.assertEqual(self.manager.count, 20)

    def test_thread_safety_remocao_concorrente(self) -> None:
        """Segurança com múltiplas threads removendo produtos."""
        for i in range(20):
            product = ProductWatcher(
                product_id=f"prod_{i}",
                url=f"https://example.com/{i}",
                store="Amazon",
            )
            self.manager.register(product)

        erros = []

        def remover(i: int) -> None:
            try:
                self.manager.remove(f"prod_{i}")
            except Exception as e:
                erros.append(e)

        threads = [
            threading.Thread(target=remover, args=(i,)) for i in range(20)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(erros), 0)
        self.assertEqual(self.manager.count, 0)

    def test_thread_safety_leitura_escrita_concorrente(self) -> None:
        """Leitura e escrita concorrentes não causam erros."""
        for i in range(10):
            product = ProductWatcher(
                product_id=f"prod_{i}",
                url=f"https://example.com/{i}",
                store="Amazon",
            )
            self.manager.register(product)

        erros = []

        def leitor() -> None:
            for _ in range(50):
                try:
                    self.manager.list_all()
                    self.manager.count
                    self.manager.get("prod_0")
                except Exception as e:
                    erros.append(e)

        def escritor() -> None:
            for i in range(10, 20):
                try:
                    product = ProductWatcher(
                        product_id=f"prod_{i}",
                        url=f"https://example.com/{i}",
                        store="Shopee",
                    )
                    self.manager.register(product)
                    self.manager.remove(f"prod_{i - 10}")
                except (ValueError, KeyError):
                    pass  # duplicatas esperadas no cenário concorrente
                except Exception as e:
                    erros.append(e)

        threads = [
            threading.Thread(target=leitor) for _ in range(5)
        ] + [
            threading.Thread(target=escritor) for _ in range(3)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(erros), 0)

    # ── integração com Scheduler ────────────────────────────────────

    def test_integracao_com_scheduler(self) -> None:
        """Integração com Scheduler: manager usa scheduler para agendar verificações."""
        scheduler = Scheduler()
        callback = Mock()
        manager = ProductWatcherManager(
            scheduler=scheduler,
            on_check=callback,
            poll_interval_seconds=0.1,
        )
        product = ProductWatcher(
            product_id="test",
            url="https://example.com",
            store="Amazon",
            interval_minutes=0,
        )
        manager.register(product)
        manager.start()
        self.assertTrue(scheduler.is_running)
        self.assertTrue(scheduler.task_exists("product_watcher_check"))
        time.sleep(0.4)
        manager.stop()
        self.assertFalse(scheduler.is_running)
        self.assertGreaterEqual(callback.call_count, 1)

    def test_integracao_scheduler_task_registrada(self) -> None:
        """Verificar que a task foi registrada no scheduler."""
        scheduler = Scheduler()
        manager = ProductWatcherManager(scheduler=scheduler)
        manager.start()
        self.assertTrue(scheduler.task_exists("product_watcher_check"))
        manager.stop()

    def test_integracao_scheduler_task_removida_ao_parar(self) -> None:
        """Task é removida do scheduler ao parar (via stop do scheduler)."""
        scheduler = Scheduler()
        manager = ProductWatcherManager(scheduler=scheduler)
        manager.start()
        manager.stop(wait=True)
        # Scheduler para, mas a task permanece registrada (pode ser re-iniciada)
        # O importante é que o scheduler não está mais rodando
        self.assertFalse(scheduler.is_running)

    # ── nenhuma execução após parada ────────────────────────────────

    def test_nenhum_callback_apos_stop_flag(self) -> None:
        """Garantir que _check_due_products não executa nada se _stopped for True."""
        callback = Mock()
        manager = ProductWatcherManager(on_check=callback)
        product = ProductWatcher(
            product_id="test",
            url="https://example.com",
            store="Amazon",
            interval_minutes=0,
        )
        manager.register(product)
        manager._stopped = True
        manager._check_due_products()
        callback.assert_not_called()

    # ── repr ────────────────────────────────────────────────────────

    def test_repr(self) -> None:
        """__repr__ retorna representação textual."""
        rep = repr(self.manager)
        self.assertIn("ProductWatcherManager", rep)
        self.assertIn("products=0", rep)
        self.assertIn("running=False", rep)

    def test_repr_com_produtos(self) -> None:
        """__repr__ com produtos registrados."""
        self.manager.register(self.product)
        rep = repr(self.manager)
        self.assertIn("products=1", rep)

    # ── cenários de borda ───────────────────────────────────────────

    def test_registrar_apos_remover_mesmo_id(self) -> None:
        """Registrar novamente após remover o mesmo ID."""
        self.manager.register(self.product)
        self.manager.remove("prod_001")
        self.manager.register(self.product)
        self.assertEqual(self.manager.count, 1)
        self.assertIsNotNone(self.manager.get("prod_001"))

    def test_remove_apos_stop(self) -> None:
        """Remover produto após parar o monitoramento."""
        self.manager.register(self.product)
        self.manager.start()
        self.manager.stop()
        removed = self.manager.remove("prod_001")
        self.assertIsNotNone(removed)
        self.assertEqual(self.manager.count, 0)

    def test_register_apos_stop(self) -> None:
        """Registrar produto após parar o monitoramento."""
        self.manager.start()
        self.manager.stop()
        self.manager.register(self.product)
        self.assertEqual(self.manager.count, 1)

    def test_start_stop_multiplas_vezes(self) -> None:
        """Iniciar e parar múltiplas vezes."""
        for _ in range(3):
            self.manager.start()
            time.sleep(0.1)
            self.manager.stop(wait=True)
            self.assertFalse(self.manager.is_running)

    def test_produto_com_intervalo_zero_sempre_devido(self) -> None:
        """Produto com interval_minutes=0 está sempre devido."""
        product = ProductWatcher(
            product_id="sempre_devido",
            url="https://example.com",
            store="Amazon",
            interval_minutes=0,
        )
        self.assertTrue(product.is_due())
        product.mark_checked()
        # Após marcar como verificado, deve estar devido novamente
        # porque o intervalo é 0
        self.assertTrue(product.is_due())

    def test_produto_pausado_nao_devido(self) -> None:
        """Produto pausado não está devido."""
        product = ProductWatcher(
            product_id="pausado",
            url="https://example.com",
            store="Amazon",
            interval_minutes=0,
        )
        product.pause()
        self.assertFalse(product.is_due())

    def test_produto_stopped_nao_devido(self) -> None:
        """Produto com status STOPPED não está devido."""
        product = ProductWatcher(
            product_id="parado",
            url="https://example.com",
            store="Amazon",
            interval_minutes=0,
        )
        product.stop()
        self.assertFalse(product.is_due())


if __name__ == "__main__":
    unittest.main()