"""
MonitorManager — orquestrador principal do módulo de monitoramento.

Coordena ProductWatchers e MonitorScheduler expondo uma API de alto
nível para iniciar/parar monitoramento, registrar produtos, controlar
intervalos e preparar o terreno para eventos futuros (scraping,
notificações, persistência).

Integração completa com ProductWatcherManager:
    - ProductWatcherManager é usado internamente para gerenciar
      watchers individuais com callbacks de verificação.
    - MonitorManager orquestra o ciclo de vida completo.
    - start_all() inicia todos os monitores registrados.
    - stop_all() para todos os monitores de forma segura.

NÃO contém lógica de scraping — apenas orquestração.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

from src.monitor.scheduler import MonitorScheduler
from src.monitor.watcher import ProductWatcher, ProductWatcherManager, WatcherStatus

logger = logging.getLogger(__name__)


@dataclass
class MonitorStats:
    """Estatísticas consolidadas do estado atual do monitor."""

    total_watchers: int = 0
    active: int = 0
    paused: int = 0
    errored: int = 0
    stopped: int = 0
    running: bool = False
    last_cycle: Optional[str] = None
    total_checks: int = 0
    total_errors: int = 0


class MonitorManager:
    """
    Gerencia o ciclo de vida completo do monitoramento inteligente.

    Responsabilidades:
        - Iniciar / parar o loop de verificação.
        - Registrar / remover produtos (ProductWatcher).
        - Alterar intervalo de atualização de watchers individuais.
        - Iniciar / parar todos os monitores registrados (start_all / stop_all).
        - Expor estatísticas e status.
        - Servir de ponto de extensão para callbacks de scraping futuro.

    Uso típico:
        manager = MonitorManager()
        manager.register_product("p1", "https://...", "Amazon", label="SSD 1TB")
        manager.set_interval("p1", 120)    # verificar a cada 2h
        manager.start_all()
        # ... em outro thread ou via loop ...
        manager.stop_all()
    """

    def __init__(
        self,
        poll_interval_seconds: float = 60.0,
        on_due_callback: Optional[Callable[[list[ProductWatcher]], None]] = None,
        on_tick_callback: Optional[Callable[[], None]] = None,
    ) -> None:
        """
        Args:
            poll_interval_seconds: Frequência do loop do scheduler.
            on_due_callback: Callable para processar watchers devidos
                (será substituído por scraping no futuro).
            on_tick_callback: Callable opcional a cada tick.
        """
        self._scheduler = MonitorScheduler(
            poll_interval_seconds=poll_interval_seconds,
            on_tick=self._on_tick,
        )
        self._watcher_manager = ProductWatcherManager(
            poll_interval_seconds=poll_interval_seconds,
            on_check=self._on_watcher_check,
        )
        self._on_due_callback = on_due_callback
        self._on_tick_callback = on_tick_callback
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._total_checks = 0
        self._total_errors = 0
        self._last_cycle: Optional[datetime] = None
        self._lock = threading.Lock()

    # ── ciclo de vida ───────────────────────────────────────────────

    def start(self) -> None:
        """
        Inicia o loop de monitoramento em uma thread daemon.

        Se já estiver rodando, é um no-op.
        """
        with self._lock:
            if self._running:
                logger.warning("MonitorManager já está rodando.")
                return
            self._running = True

        self._thread = threading.Thread(
            target=self._run_loop,
            name="monitor-manager",
            daemon=True,
        )
        self._thread.start()
        logger.info("MonitorManager iniciado.")

    def stop(self, wait: bool = True) -> None:
        """
        Para o loop de monitoramento.

        Args:
            wait: Se True, aguarda a thread finalizar.
        """
        self._scheduler.stop_loop()
        with self._lock:
            self._running = False
        if wait and self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=10)
        logger.info("MonitorManager parado.")

    @property
    def is_running(self) -> bool:
        """Indica se o loop de monitoramento está ativo."""
        return self._running

    # ── controle de todos os monitores ──────────────────────────────

    def start_all(self) -> None:
        """
        Inicia todos os monitores registrados.

        Equivalente a:
            1. Iniciar o MonitorManager (loop de verificação).
            2. Iniciar o ProductWatcherManager (verificação periódica).

        Se algum componente já estiver rodando, é ignorado (no-op).
        Garante que exceções de um monitor não interrompam os demais.
        """
        logger.info("Iniciando todos os monitores...")
        try:
            self._watcher_manager.start()
        except RuntimeError:
            # Já está rodando — não é um problema
            logger.debug("ProductWatcherManager já estava rodando.")
        except Exception as exc:
            logger.error("Erro ao iniciar ProductWatcherManager: %s", exc)

        try:
            self.start()
        except Exception as exc:
            logger.error("Erro ao iniciar MonitorManager: %s", exc)

        logger.info("Todos os monitores iniciados.")

    def stop_all(self, wait: bool = True) -> None:
        """
        Para todos os monitores de forma segura.

        Garantias:
            - Parada segura do MonitorManager.
            - Parada segura do ProductWatcherManager.
            - Limpeza de recursos (scheduler, threads).
            - Callbacks não são executados após parada.
            - Pode ser chamado mesmo se não estiver rodando.

        Args:
            wait: Se True, aguarda as threads finalizarem.
        """
        logger.info("Parando todos os monitores...")
        try:
            self.stop(wait=wait)
        except Exception as exc:
            logger.error("Erro ao parar MonitorManager: %s", exc)

        try:
            self._watcher_manager.stop(wait=wait)
        except Exception as exc:
            logger.error("Erro ao parar ProductWatcherManager: %s", exc)

        # Limpeza de recursos
        self._cleanup_resources()
        logger.info("Todos os monitores parados.")

    def _cleanup_resources(self) -> None:
        """
        Limpa recursos internos após parada.

        Garante que:
            - Nenhuma referência órfã permaneça.
            - O scheduler seja limpo.
        """
        with self._lock:
            self._thread = None
            self._total_checks = 0
            self._total_errors = 0

    # ── registro de produtos ────────────────────────────────────────

    def register_product(
        self,
        product_id: str,
        url: str,
        store: str,
        label: str = "",
        interval_minutes: int = 240,
        tags: Optional[set[str]] = None,
    ) -> ProductWatcher:
        """
        Cria e registra um novo produto para monitoramento.

        O produto é registrado tanto no MonitorScheduler quanto no
        ProductWatcherManager para garantir consistência.

        Validações:
            - product_id não pode ser vazio.
            - Evita duplicação de product_id (já registrado).
            - Evita duplicação de mesma URL + loja.
            - Intervalo deve ser >= 1 minuto.

        Returns:
            A instância de ProductWatcher criada.

        Raises:
            ValueError: Se o product_id já existir, se a combinação
                URL+loja já estiver registrada, ou se o intervalo
                for inválido.
        """
        if not product_id or not product_id.strip():
            raise ValueError("product_id não pode ser vazio.")

        # Evita duplicação de product_id
        existing_by_id = self._scheduler.get(product_id)
        if existing_by_id is not None:
            raise ValueError(
                f"Produto com ID '{product_id}' já está registrado."
            )

        # Evita duplicação de mesma URL + loja
        for watcher in self._scheduler.list_all():
            if watcher.url == url and watcher.store == store:
                raise ValueError(
                    f"Produto com URL '{url}' e loja '{store}' já está "
                    f"registrado (ID: {watcher.product_id})."
                )

        self._validate_interval(interval_minutes)

        watcher = ProductWatcher(
            product_id=product_id,
            url=url,
            store=store,
            label=label or product_id,
            interval_minutes=interval_minutes,
            tags=tags or set(),
        )
        # Registra no scheduler (para o loop do MonitorManager)
        self._scheduler.add(watcher)
        # Registra no watcher manager (para verificação periódica)
        try:
            self._watcher_manager.register(watcher)
        except ValueError:
            # Se já estiver registrado, apenas loga e continua
            logger.debug(
                "Watcher %s já registrado no ProductWatcherManager.", product_id
            )

        logger.info(
            "Produto registrado: %s (%s) na loja %s a cada %d min.",
            watcher.label,
            product_id,
            store,
            interval_minutes,
        )
        return watcher

    def unregister_product(self, product_id: str) -> Optional[ProductWatcher]:
        """
        Remove um produto do monitoramento.

        Remove tanto do MonitorScheduler quanto do ProductWatcherManager.

        Returns:
            O watcher removido, ou None se não encontrado.
        """
        removed = self._scheduler.remove(product_id)
        # Remove também do watcher manager
        self._watcher_manager.remove(product_id)
        if removed:
            logger.info("Produto removido: %s", product_id)
        else:
            logger.warning("Produto não encontrado para remoção: %s", product_id)
        return removed

    def get_product(self, product_id: str) -> Optional[ProductWatcher]:
        """Obtém um watcher pelo ID."""
        return self._scheduler.get(product_id)

    def list_products(self) -> list[ProductWatcher]:
        """Lista todos os produtos registrados."""
        return self._scheduler.list_all()

    # ── controle de intervalo ───────────────────────────────────────

    def set_interval(self, product_id: str, interval_minutes: int) -> bool:
        """
        Altera o intervalo de atualização de um produto registrado.

        Args:
            product_id: ID do produto.
            interval_minutes: Novo intervalo em minutos (mínimo 1).

        Returns:
            True se o produto foi encontrado e atualizado.

        Raises:
            ValueError: Se o intervalo for inválido (< 1 minuto).
        """
        self._validate_interval(interval_minutes)
        watcher = self._scheduler.get(product_id)
        if watcher is None:
            logger.warning("Produto não encontrado: %s", product_id)
            return False
        watcher.interval_minutes = interval_minutes
        logger.info(
            "Intervalo alterado: %s -> %d min", product_id, interval_minutes
        )
        return True

    def pause_product(self, product_id: str) -> bool:
        """Pausa o monitoramento de um produto."""
        watcher = self._scheduler.get(product_id)
        if watcher is None:
            return False
        watcher.pause()
        logger.info("Produto pausado: %s", product_id)
        return True

    def resume_product(self, product_id: str) -> bool:
        """Retoma o monitoramento de um produto pausado."""
        watcher = self._scheduler.get(product_id)
        if watcher is None:
            return False
        watcher.resume()
        # Reagenda imediatamente para próxima verificação
        self._scheduler.reschedule(watcher)
        logger.info("Produto retomado: %s", product_id)
        return True

    # ── hooks para eventos futuros ──────────────────────────────────

    def set_on_due_callback(
        self, callback: Callable[[list[ProductWatcher]], None]
    ) -> None:
        """
        Define o callback para processar watchers devidos.

        Este é o ponto de integração para o scraping futuro:
            manager.set_on_due_callback(lambda watchers: scrap(watchers))
        """
        self._on_due_callback = callback

    def set_on_tick_callback(self, callback: Callable[[], None]) -> None:
        """Define um callback opcional acionado a cada tick do loop."""
        self._on_tick_callback = callback

    # ── estatísticas ────────────────────────────────────────────────

    def stats(self) -> MonitorStats:
        """Retorna estatísticas consolidadas do monitor."""
        watchers = self._scheduler.list_all()
        active = sum(1 for w in watchers if w.is_active)
        paused = sum(1 for w in watchers if w.is_paused)
        errored = sum(1 for w in watchers if w.status == WatcherStatus.ERROR)
        stopped = sum(1 for w in watchers if w.status == WatcherStatus.STOPPED)

        return MonitorStats(
            total_watchers=len(watchers),
            active=active,
            paused=paused,
            errored=errored,
            stopped=stopped,
            running=self._running,
            last_cycle=self._last_cycle.isoformat() if self._last_cycle else None,
            total_checks=self._total_checks,
            total_errors=self._total_errors,
        )

    # ── métodos internos ────────────────────────────────────────────

    def _on_tick(self) -> None:
        """Callback interno acionado pelo scheduler a cada tick."""
        if self._on_tick_callback:
            try:
                self._on_tick_callback()
            except Exception as exc:
                logger.error("Erro no on_tick_callback: %s", exc)

    def _on_watcher_check(self, watcher: ProductWatcher) -> None:
        """
        Callback interno acionado pelo ProductWatcherManager
        quando um watcher está devido para verificação.

        Se o Manager estiver parado, não executa a callback.
        Erros são logados e não interrompem outros watchers.
        """
        if not self._running:
            logger.debug(
                "MonitorManager parado — ignorando watcher %s.", watcher.product_id
            )
            return

        if self._on_due_callback:
            try:
                self._on_due_callback([watcher])
                watcher.mark_checked()
            except Exception as exc:
                logger.error(
                    "Erro ao processar watcher '%s': %s",
                    watcher.product_id,
                    exc,
                )
                watcher.mark_error()
                with self._lock:
                    self._total_errors += 1
        else:
            logger.info(
                "[placeholder] %d watcher(s) devido(s) - "
                "nenhum callback de scraping registrado.",
                1,
            )

    def _run_loop(self) -> None:
        """Executa o loop principal delegando ao scheduler."""
        self._scheduler.run_loop(
            on_due=self._handle_due,
            stop_event=None,  # usa o stop_event interno do scheduler
        )

    def _handle_due(self, watchers: list[ProductWatcher]) -> None:
        """
        Processa uma lista de watchers devidos.

        1. Se um callback externo foi registrado, chama-o.
        2. Caso contrário, apenas loga (placeholder para scraping futuro).
        3. Reagenda cada watcher após o processamento.
        """
        with self._lock:
            self._total_checks += len(watchers)
            self._last_cycle = datetime.now()

        if self._on_due_callback:
            try:
                self._on_due_callback(watchers)
            except Exception as exc:
                logger.error("Erro no on_due_callback: %s", exc)
                for w in watchers:
                    w.mark_error()
                    self._total_errors += 1
        else:
            # Placeholder: apenas loga que os watchers estão devidos
            logger.info(
                "[placeholder] %d watcher(s) devido(s) - "
                "nenhum callback de scraping registrado.",
                len(watchers),
            )

        # Reagenda todos (exceto os que entraram em estado de erro máximo)
        for w in watchers:
            if w.status == WatcherStatus.ERROR:
                logger.warning(
                    "Watcher %s atingiu limite de erros e será pausado.", w.product_id
                )
                continue
            self._scheduler.reschedule(w)

    # ── validação de intervalo ────────────────────────────────────

    @staticmethod
    def _validate_interval(minutes: int) -> None:
        """
        Valida que o intervalo em minutos é um valor positivo.

        Raises:
            ValueError: Se minutos < 1.
        """
        if not isinstance(minutes, int):
            raise ValueError(
                f"Intervalo deve ser um número inteiro, recebeu {type(minutes).__name__}."
            )
        if minutes < 1:
            raise ValueError(
                f"Intervalo mínimo é 1 minuto, recebeu {minutes}."
            )

    # ── dunder ──────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"<MonitorManager running={self._running} "
            f"watchers={self._scheduler.count}>"
        )
