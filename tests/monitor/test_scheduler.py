"""
Testes para o Scheduler — agendador independente e thread-safe.

Cobre:
    - Criação do Scheduler
    - Registro de tarefa
    - Registro duplicado
    - Intervalo inválido
    - Remoção
    - Consulta
    - Listagem
    - Início
    - Parada
    - Dupla inicialização
    - Execução periódica
    - Callback com erro
    - Mais de uma tarefa
    - Nenhuma execução após parada
    - Segurança básica com múltiplas threads
"""

from __future__ import annotations

import threading
import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock

from src.monitor.scheduler import Scheduler, ScheduledTask


class SchedulerTest(unittest.TestCase):
    """Testes unitários para o Scheduler."""

    def setUp(self) -> None:
        self.scheduler = Scheduler()

    def tearDown(self) -> None:
        if self.scheduler.is_running:
            self.scheduler.stop(wait=True)

    # ── criação ─────────────────────────────────────────────────────

    def test_criacao_do_scheduler(self) -> None:
        """Criação do Scheduler."""
        sched = Scheduler()
        self.assertIsNotNone(sched)
        self.assertFalse(sched.is_running)
        self.assertEqual(sched.task_count, 0)

    # ── registro ────────────────────────────────────────────────────

    def test_registro_de_tarefa(self) -> None:
        """Registro de tarefa com callback e intervalo."""
        callback = Mock()
        self.scheduler.register("task1", callback, interval_seconds=30)
        self.assertEqual(self.scheduler.task_count, 1)
        self.assertTrue(self.scheduler.task_exists("task1"))

    def test_registro_duplicado(self) -> None:
        """Impedir identificadores duplicados."""
        callback = Mock()
        self.scheduler.register("task1", callback, interval_seconds=30)
        with self.assertRaises(ValueError) as ctx:
            self.scheduler.register("task1", callback, interval_seconds=60)
        self.assertIn("já está registrada", str(ctx.exception))

    def test_registro_com_task_id_vazio(self) -> None:
        """Registro com task_id vazio é rejeitado."""
        callback = Mock()
        with self.assertRaises(ValueError) as ctx:
            self.scheduler.register("", callback, interval_seconds=30)
        self.assertIn("não pode ser vazio", str(ctx.exception))

    def test_registro_com_task_id_espacos(self) -> None:
        """Registro com task_id de espaços é rejeitado."""
        callback = Mock()
        with self.assertRaises(ValueError) as ctx:
            self.scheduler.register("   ", callback, interval_seconds=30)
        self.assertIn("não pode ser vazio", str(ctx.exception))

    # ── intervalo inválido ──────────────────────────────────────────

    def test_intervalo_invalido_zero(self) -> None:
        """Rejeitar intervalo igual a zero."""
        callback = Mock()
        with self.assertRaises(ValueError) as ctx:
            self.scheduler.register("task1", callback, interval_seconds=0)
        self.assertIn("maior que zero", str(ctx.exception))

    def test_intervalo_invalido_negativo(self) -> None:
        """Rejeitar intervalo negativo."""
        callback = Mock()
        with self.assertRaises(ValueError) as ctx:
            self.scheduler.register("task1", callback, interval_seconds=-10)
        self.assertIn("maior que zero", str(ctx.exception))

    def test_intervalo_invalido_nao_numerico(self) -> None:
        """Rejeitar intervalo não numérico."""
        callback = Mock()
        with self.assertRaises(ValueError) as ctx:
            self.scheduler.register("task1", callback, interval_seconds="abc")  # type: ignore
        self.assertIn("deve ser um número", str(ctx.exception))

    def test_intervalo_valido_float(self) -> None:
        """Aceitar intervalo como float."""
        callback = Mock()
        self.scheduler.register("task1", callback, interval_seconds=0.5)
        self.assertEqual(self.scheduler.task_count, 1)

    # ── remoção ─────────────────────────────────────────────────────

    def test_remocao_de_tarefa(self) -> None:
        """Remover tarefa pelo identificador."""
        callback = Mock()
        self.scheduler.register("task1", callback, interval_seconds=30)
        removed = self.scheduler.remove("task1")
        self.assertIsNotNone(removed)
        self.assertEqual(removed.task_id, "task1")
        self.assertFalse(self.scheduler.task_exists("task1"))
        self.assertEqual(self.scheduler.task_count, 0)

    def test_remocao_de_tarefa_inexistente(self) -> None:
        """Remover tarefa que não existe retorna None."""
        removed = self.scheduler.remove("nao_existe")
        self.assertIsNone(removed)

    # ── consulta ────────────────────────────────────────────────────

    def test_consulta_de_tarefa(self) -> None:
        """Consultar se uma tarefa existe."""
        callback = Mock()
        self.scheduler.register("task1", callback, interval_seconds=30)
        self.assertTrue(self.scheduler.task_exists("task1"))
        self.assertFalse(self.scheduler.task_exists("nao_existe"))

    def test_get_task_retorna_tarefa_correta(self) -> None:
        """get_task retorna a tarefa pelo ID."""
        callback = Mock()
        self.scheduler.register("task1", callback, interval_seconds=30)
        task = self.scheduler.get_task("task1")
        self.assertIsNotNone(task)
        self.assertEqual(task.task_id, "task1")
        self.assertEqual(task.interval_seconds, 30)

    def test_get_task_inexistente_retorna_none(self) -> None:
        """get_task para ID inexistente retorna None."""
        self.assertIsNone(self.scheduler.get_task("nao_existe"))

    # ── listagem ────────────────────────────────────────────────────

    def test_listagem_de_tarefas(self) -> None:
        """Listar tarefas registradas."""
        callback = Mock()
        self.scheduler.register("task1", callback, interval_seconds=30)
        self.scheduler.register("task2", callback, interval_seconds=60)
        tasks = self.scheduler.list_tasks()
        self.assertEqual(len(tasks), 2)
        ids = {t.task_id for t in tasks}
        self.assertIn("task1", ids)
        self.assertIn("task2", ids)

    def test_listagem_vazia(self) -> None:
        """Listar tarefas sem registros retorna lista vazia."""
        self.assertEqual(self.scheduler.list_tasks(), [])

    # ── início ──────────────────────────────────────────────────────

    def test_inicio_do_scheduler(self) -> None:
        """Iniciar o Scheduler."""
        self.assertFalse(self.scheduler.is_running)
        self.scheduler.start()
        self.assertTrue(self.scheduler.is_running)
        self.scheduler.stop()
        self.assertFalse(self.scheduler.is_running)

    def test_dupla_inicializacao(self) -> None:
        """Impedir dupla inicialização."""
        self.scheduler.start()
        with self.assertRaises(RuntimeError) as ctx:
            self.scheduler.start()
        self.assertIn("já está em execução", str(ctx.exception))
        self.scheduler.stop()

    # ── parada ──────────────────────────────────────────────────────

    def test_parada_do_scheduler(self) -> None:
        """Parar o Scheduler de forma segura."""
        self.scheduler.start()
        time.sleep(0.05)
        self.scheduler.stop(wait=True)
        self.assertFalse(self.scheduler.is_running)

    def test_parar_sem_iniciar_nao_gera_erro(self) -> None:
        """Parar o scheduler sem ter iniciado não gera erro."""
        self.scheduler.stop()  # não deve levantar exceção
        self.assertFalse(self.scheduler.is_running)

    # ── execução periódica ──────────────────────────────────────────

    def test_execucao_periodica(self) -> None:
        """Permitir execução periódica sem bloquear a thread principal."""
        callback = Mock()
        self.scheduler.register("task1", callback, interval_seconds=0.1)
        self.scheduler.start()
        time.sleep(0.6)
        self.scheduler.stop()
        # Deve ter executado pelo menos 3 vezes (0.1s de intervalo em 0.6s)
        self.assertGreaterEqual(callback.call_count, 3)

    def test_mais_de_uma_tarefa(self) -> None:
        """Mais de uma tarefa executando simultaneamente."""
        callback1 = Mock()
        callback2 = Mock()
        self.scheduler.register("task1", callback1, interval_seconds=0.1)
        self.scheduler.register("task2", callback2, interval_seconds=0.15)
        self.scheduler.start()
        time.sleep(0.7)
        self.scheduler.stop()
        self.assertGreaterEqual(callback1.call_count, 3)
        self.assertGreaterEqual(callback2.call_count, 2)

    # ── callback com erro ───────────────────────────────────────────

    def test_callback_com_erro_nao_interrompe_outras(self) -> None:
        """Isolar erros das callbacks: uma com erro não interrompe as demais."""
        callback_ok = Mock()
        callback_falha = Mock(side_effect=RuntimeError("Erro simulado"))

        self.scheduler.register("ok", callback_ok, interval_seconds=0.1)
        self.scheduler.register("falha", callback_falha, interval_seconds=0.1)
        self.scheduler.start()
        time.sleep(0.6)
        self.scheduler.stop()

        # A callback que falha deve ter sido chamada
        self.assertGreaterEqual(callback_falha.call_count, 2)
        # A callback ok deve continuar executando
        self.assertGreaterEqual(callback_ok.call_count, 2)

    # ── nenhuma execução após parada ────────────────────────────────

    def test_nenhuma_execucao_apos_parada(self) -> None:
        """Não executar tarefas após o Scheduler ser parado."""
        callback = Mock()
        self.scheduler.register("task1", callback, interval_seconds=0.1)
        self.scheduler.start()
        time.sleep(0.3)
        self.scheduler.stop(wait=True)
        # Conta quantas vezes foi chamado até parar
        chamadas_ate_parar = callback.call_count
        time.sleep(0.3)
        # Não deve ter chamado novamente após parar
        self.assertEqual(callback.call_count, chamadas_ate_parar)

    # ── segurança com múltiplas threads ─────────────────────────────

    def test_seguranca_com_multiplas_threads(self) -> None:
        """Segurança básica com múltiplas threads registrando tarefas."""
        resultados: list[bool] = []
        lock = threading.Lock()

        def registrar(i: int) -> None:
            try:
                self.scheduler.register(
                    f"task_{i}",
                    lambda: None,
                    interval_seconds=1,
                )
                with lock:
                    resultados.append(True)
            except Exception:
                with lock:
                    resultados.append(False)

        threads = [
            threading.Thread(target=registrar, args=(i,))
            for i in range(20)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Pelo menos 1 deve ter registrado com sucesso
        self.assertGreater(sum(resultados), 0)
        # Nenhum erro inesperado
        self.assertGreater(self.scheduler.task_count, 0)

    # ── propriedades ────────────────────────────────────────────────

    def test_task_count_property(self) -> None:
        """Propriedade task_count retorna quantidade correta."""
        callback = Mock()
        self.assertEqual(self.scheduler.task_count, 0)
        self.scheduler.register("task1", callback, interval_seconds=30)
        self.assertEqual(self.scheduler.task_count, 1)
        self.scheduler.register("task2", callback, interval_seconds=60)
        self.assertEqual(self.scheduler.task_count, 2)
        self.scheduler.remove("task1")
        self.assertEqual(self.scheduler.task_count, 1)

    def test_is_running_property(self) -> None:
        """Propriedade is_running reflete estado correto."""
        self.assertFalse(self.scheduler.is_running)
        self.scheduler.start()
        self.assertTrue(self.scheduler.is_running)
        self.scheduler.stop()
        self.assertFalse(self.scheduler.is_running)

    def test_repr(self) -> None:
        """__repr__ retorna representação textual."""
        rep = repr(self.scheduler)
        self.assertIn("Scheduler", rep)
        self.assertIn("running=False", rep)
        self.assertIn("tasks=0", rep)

    def test_repr_com_tarefas(self) -> None:
        """__repr__ com tarefas registradas."""
        callback = Mock()
        self.scheduler.register("task1", callback, interval_seconds=30)
        rep = repr(self.scheduler)
        self.assertIn("tasks=1", rep)

    # ── cenários de borda ───────────────────────────────────────────

    def test_registrar_apos_remover_mesmo_id(self) -> None:
        """Registrar novamente após remover o mesmo ID."""
        callback = Mock()
        self.scheduler.register("task1", callback, interval_seconds=30)
        self.scheduler.remove("task1")
        self.scheduler.register("task1", callback, interval_seconds=60)
        self.assertTrue(self.scheduler.task_exists("task1"))
        task = self.scheduler.get_task("task1")
        self.assertEqual(task.interval_seconds, 60)

    def test_remove_apos_stop(self) -> None:
        """Remover tarefa após parar o scheduler."""
        callback = Mock()
        self.scheduler.register("task1", callback, interval_seconds=30)
        self.scheduler.start()
        self.scheduler.stop()
        removed = self.scheduler.remove("task1")
        self.assertIsNotNone(removed)
        self.assertEqual(self.scheduler.task_count, 0)

    def test_register_apos_stop(self) -> None:
        """Registrar tarefa após parar o scheduler."""
        callback = Mock()
        self.scheduler.start()
        self.scheduler.stop()
        self.scheduler.register("task1", callback, interval_seconds=30)
        self.assertEqual(self.scheduler.task_count, 1)

    def test_start_stop_multiplas_vezes(self) -> None:
        """Iniciar e parar múltiplas vezes."""
        callback = Mock()
        self.scheduler.register("task1", callback, interval_seconds=0.1)
        for _ in range(3):
            self.scheduler.start()
            time.sleep(0.25)
            self.scheduler.stop(wait=True)
            self.assertFalse(self.scheduler.is_running)

    def test_callback_recebe_chamadas_repetidas(self) -> None:
        """Callback é chamado repetidamente no intervalo definido."""
        contador = [0]
        lock = threading.Lock()

        def incrementar() -> None:
            with lock:
                contador[0] += 1

        self.scheduler.register("contador", incrementar, interval_seconds=0.1)
        self.scheduler.start()
        time.sleep(0.6)
        self.scheduler.stop()
        with lock:
            self.assertGreaterEqual(contador[0], 3)


if __name__ == "__main__":
    unittest.main()