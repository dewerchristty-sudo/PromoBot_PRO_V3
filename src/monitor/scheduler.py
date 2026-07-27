"""
MonitorScheduler — controle de intervalo e agenda de verificações.

Gerencia quando cada ProductWatcher deve ser verificado, respeitando
intervalos individuais e fornecendo uma fila prioritária de watchers
"devidos". Opera de forma puramente temporal — sem scraping.
"""

from __future__ import annotations

import heapq
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from threading import Event, Lock
from typing import Callable, Optional

from src.monitor.watcher import ProductWatcher

logger = logging.getLogger(__name__)


@dataclass(order=True)
class _ScheduledItem:
    """Item interno da fila de prioridade."""

    next_run: datetime
    watcher: ProductWatcher = field(compare=False)


class MonitorScheduler:
    """
    Agenda verificações de ProductWatchers com intervalos configuráveis.

    Características:
        - Fila prioritária baseada em next_check de cada watcher.
        - Suporta múltiplos watchers com intervalos diferentes.
        - Thread-safe para operações concorrentes.
        - Callback opcional acionado a cada ciclo.

    Uso típico:
        scheduler = MonitorScheduler()
        scheduler.add(watcher)
        due = scheduler.pop_due()        # watchers prontos agora
        scheduler.reschedule(watcher)     # reagenda após verificar
    """

    def __init__(
        self,
        poll_interval_seconds: float = 60.0,
        on_tick: Optional[Callable[[], None]] = None,
    ) -> None:
        """
        Args:
            poll_interval_seconds: Intervalo do loop principal (segundos).
            on_tick: Callable opcional invocada a cada tick do loop.
        """
        self._poll_interval = poll_interval_seconds
        self._on_tick = on_tick
        self._queue: list[_ScheduledItem] = []
        self._lock = Lock()
        self._stop_event = Event()
        self._watchers: dict[str, ProductWatcher] = {}

    # ── registro / remoção ──────────────────────────────────────────

    def add(self, watcher: ProductWatcher) -> None:
        """
        Adiciona um watcher ao scheduler.

        Se o watcher já existir (mesmo product_id), ele é substituído.
        """
        with self._lock:
            self._watchers[watcher.product_id] = watcher
            next_time = watcher.next_check or datetime.now()
            heapq.heappush(self._queue, _ScheduledItem(next_run=next_time, watcher=watcher))

    def remove(self, product_id: str) -> Optional[ProductWatcher]:
        """
        Remove um watcher pelo product_id.

        Returns:
            O watcher removido, ou None se não encontrado.
        """
        with self._lock:
            removed = self._watchers.pop(product_id, None)
            # Reconstroi a fila (remoção lazy — rebuild é mais seguro
            # que remover do heap em O(n) com busca linear).
            if removed is not None:
                self._rebuild_queue()
            return removed

    def get(self, product_id: str) -> Optional[ProductWatcher]:
        """Retorna o watcher pelo ID, sem removê-lo."""
        with self._lock:
            return self._watchers.get(product_id)

    def list_all(self) -> list[ProductWatcher]:
        """Retorna uma cópia da lista de todos os watchers registrados."""
        with self._lock:
            return list(self._watchers.values())

    def clear(self) -> None:
        """Remove todos os watchers do scheduler."""
        with self._lock:
            self._watchers.clear()
            self._queue.clear()

    @property
    def count(self) -> int:
        """Número de watchers registrados."""
        with self._lock:
            return len(self._watchers)

    # ── fila de devidos ─────────────────────────────────────────────

    def pop_due(
        self,
        max_items: int = 0,
        reference: Optional[datetime] = None,
    ) -> list[ProductWatcher]:
        """
        Retorna (e remove da fila) os watchers que estão "devidos" agora.

        Args:
            max_items: Máximo de itens para retornar. 0 = sem limite.
            reference: Referência temporal (padrão = datetime.now()).

        Returns:
            Lista de watchers prontos para verificação.
        """
        ref = reference or datetime.now()
        due: list[ProductWatcher] = []
        with self._lock:
            while self._queue and self._queue[0].next_run <= ref:
                item = heapq.heappop(self._queue)
                # Verifica se o watcher ainda está registrado (pode ter
                # sido removido enquanto estava na fila).
                if item.watcher.product_id in self._watchers:
                    due.append(item.watcher)
                    if max_items > 0 and len(due) >= max_items:
                        break
        return due

    def peek_next(self) -> Optional[datetime]:
        """
        Retorna o timestamp do próximo watcher na fila, ou None se vazia.
        Útil para loops dormirem até o próximo evento.
        """
        with self._lock:
            return self._queue[0].next_run if self._queue else None

    def reschedule(self, watcher: ProductWatcher) -> None:
        """
        Reagenda um watcher após sua verificação.

        Atualiza next_check do watcher e reinsere na fila prioritária.
        Se o watcher estiver PAUSED ou STOPPED, não é reagendado.
        """
        if not watcher.is_active:
            return
        if watcher.next_check is None:
            now = datetime.now()
            watcher.next_check = datetime.fromtimestamp(
                now.timestamp() + watcher.interval_minutes * 60
            )
        with self._lock:
            heapq.heappush(
                self._queue,
                _ScheduledItem(next_run=watcher.next_check, watcher=watcher),
            )

    # ── loop principal ──────────────────────────────────────────────

    def run_loop(
        self,
        on_due: Callable[[list[ProductWatcher]], None],
        stop_event: Optional[Event] = None,
    ) -> None:
        """
        Loop principal que drena watchers devidos em intervalos fixos.

        Args:
            on_due: Callable recebendo a lista de watchers devidos.
            stop_event: Event para interromper o loop externamente.
        """
        effective_stop = stop_event or self._stop_event
        effective_stop.clear()
        logger.debug(
            "MonitorScheduler.run_loop iniciado (poll_interval=%.1fs).",
            self._poll_interval,
        )

        while not effective_stop.is_set():
            due = self.pop_due()
            if due:
                logger.debug(
                    "MonitorScheduler: %d watcher(s) devido(s).", len(due)
                )
                on_due(due)
            if self._on_tick:
                self._on_tick()
            effective_stop.wait(self._poll_interval)

        logger.debug("MonitorScheduler.run_loop finalizado.")

    def stop_loop(self) -> None:
        """Sinaliza para o loop principal parar."""
        self._stop_event.set()

    # ── utilitários internos ────────────────────────────────────────

    def _rebuild_queue(self) -> None:
        """Reconstrói a fila prioritária a partir dos watchers registrados."""
        self._queue.clear()
        now = datetime.now()
        for watcher in self._watchers.values():
            next_time = watcher.next_check or now
            heapq.heappush(self._queue, _ScheduledItem(next_run=next_time, watcher=watcher))

    def __len__(self) -> int:
        return self.count

    def __repr__(self) -> str:
        return f"<MonitorScheduler watchers={self.count} pending={len(self._queue)}>"


# ═══════════════════════════════════════════════════════════════════
# Scheduler — agendador independente e thread-safe
# ═══════════════════════════════════════════════════════════════════

@dataclass
class ScheduledTask:
    """
    Representa uma tarefa agendada no Scheduler.

    Attributes:
        task_id: Identificador único da tarefa.
        callback: Função a ser executada periodicamente.
        interval_seconds: Intervalo entre execuções em segundos.
        last_run: Timestamp da última execução.
        next_run: Timestamp da próxima execução.
    """

    task_id: str
    callback: Callable[[], None]
    interval_seconds: float
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None


class Scheduler:
    """
    Agendador simples, modular, thread-safe e independente.

    Gerencia tarefas que executam callbacks em intervalos fixos,
    sem depender de ProductWatcher ou MonitorManager.

    Uso típico:
        sched = Scheduler()
        sched.register("task1", my_callback, interval_seconds=30)
        sched.start()
        # ... em outra thread ...
        sched.stop()
    """

    def __init__(self) -> None:
        self._tasks: dict[str, ScheduledTask] = {}
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._running = False

    # ── registro / remoção ──────────────────────────────────────────

    def register(
        self,
        task_id: str,
        callback: Callable[[], None],
        interval_seconds: float,
    ) -> None:
        """
        Registra uma nova tarefa no scheduler.

        Args:
            task_id: Identificador único da tarefa.
            callback: Função a ser executada periodicamente.
            interval_seconds: Intervalo entre execuções em segundos.

        Raises:
            ValueError: Se task_id já estiver registrado ou se o
                intervalo for inválido.
        """
        if not task_id or not task_id.strip():
            raise ValueError("task_id não pode ser vazio.")

        self._validate_interval(interval_seconds)

        with self._lock:
            if task_id in self._tasks:
                raise ValueError(
                    f"Tarefa com ID '{task_id}' já está registrada."
                )
            now = datetime.now()
            task = ScheduledTask(
                task_id=task_id,
                callback=callback,
                interval_seconds=interval_seconds,
                next_run=now + timedelta(seconds=interval_seconds),
            )
            self._tasks[task_id] = task

    def remove(self, task_id: str) -> Optional[ScheduledTask]:
        """
        Remove uma tarefa pelo identificador.

        Returns:
            A tarefa removida, ou None se não encontrada.
        """
        with self._lock:
            return self._tasks.pop(task_id, None)

    def get_task(self, task_id: str) -> Optional[ScheduledTask]:
        """Retorna uma tarefa pelo ID, sem removê-la."""
        with self._lock:
            return self._tasks.get(task_id)

    def list_tasks(self) -> list[ScheduledTask]:
        """Retorna uma cópia da lista de todas as tarefas registradas."""
        with self._lock:
            return list(self._tasks.values())

    def task_exists(self, task_id: str) -> bool:
        """Verifica se uma tarefa com o ID informado existe."""
        with self._lock:
            return task_id in self._tasks

    # ── ciclo de vida ───────────────────────────────────────────────

    def start(self) -> None:
        """
        Inicia o loop de execução em uma thread daemon.

        Se já estiver rodando, levanta RuntimeError.
        """
        with self._lock:
            if self._running:
                raise RuntimeError("Scheduler já está em execução.")
            self._running = True
            self._stop_event.clear()

        self._thread = threading.Thread(
            target=self._run_loop,
            name="scheduler",
            daemon=True,
        )
        self._thread.start()

    def stop(self, wait: bool = True) -> None:
        """
        Para o loop de execução de forma segura.

        Args:
            wait: Se True, aguarda a thread finalizar.
        """
        self._stop_event.set()
        with self._lock:
            self._running = False
        if wait and self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=10)

    @property
    def is_running(self) -> bool:
        """Indica se o scheduler está em execução."""
        return self._running

    @property
    def task_count(self) -> int:
        """Número de tarefas registradas."""
        with self._lock:
            return len(self._tasks)

    # ── loop interno ────────────────────────────────────────────────

    def _run_loop(self) -> None:
        """Loop principal que executa tarefas devidas."""
        while not self._stop_event.is_set():
            due = self._pop_due()
            for task in due:
                self._execute_task(task)
            # Aguarda um pequeno intervalo antes de verificar novamente
            self._stop_event.wait(0.05)

    def _pop_due(self) -> list[ScheduledTask]:
        """
        Retorna as tarefas que estão devidas para execução.

        Uma tarefa está devida quando:
        - Nunca foi executada (last_run is None), ou
        - O tempo desde last_run ultrapassou interval_seconds.

        Atualiza last_run e next_run de cada tarefa devida.
        """
        now = datetime.now()
        due: list[ScheduledTask] = []
        with self._lock:
            for task in list(self._tasks.values()):
                is_due = (
                    task.last_run is None
                    or (now - task.last_run).total_seconds() >= task.interval_seconds
                )
                if is_due:
                    task.last_run = now
                    task.next_run = now + timedelta(seconds=task.interval_seconds)
                    due.append(task)
        return due

    def _execute_task(self, task: ScheduledTask) -> None:
        """
        Executa o callback de uma tarefa, isolando erros.

        Se o callback levantar exceção, ela é logada e não
        interrompe as demais tarefas.
        """
        try:
            task.callback()
        except Exception as exc:
            logger.error(
                "Erro na tarefa '%s': %s", task.task_id, exc,
            )

    # ── validação ───────────────────────────────────────────────────

    @staticmethod
    def _validate_interval(seconds: float) -> None:
        """
        Valida que o intervalo em segundos é um número positivo.

        Raises:
            ValueError: Se seconds <= 0 ou não for numérico.
        """
        if not isinstance(seconds, (int, float)):
            raise ValueError(
                f"Intervalo deve ser um número, recebeu {type(seconds).__name__}."
            )
        if seconds <= 0:
            raise ValueError(
                f"Intervalo deve ser maior que zero, recebeu {seconds}."
            )

    # ── dunder ──────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"<Scheduler running={self._running} tasks={self.task_count}>"
        )