"""
MonitorScheduler — controle de intervalo e agenda de verificações.

Gerencia quando cada ProductWatcher deve ser verificado, respeitando
intervalos individuais e fornecendo uma fila prioritária de watchers
"devidos". Opera de forma puramente temporal — sem scraping.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from threading import Event, Lock
from typing import Callable, Optional

from src.monitor.watcher import ProductWatcher


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

        while not effective_stop.is_set():
            due = self.pop_due()
            if due:
                on_due(due)
            if self._on_tick:
                self._on_tick()
            effective_stop.wait(self._poll_interval)

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