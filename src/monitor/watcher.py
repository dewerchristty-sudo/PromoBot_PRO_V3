"""
ProductWatcher — representa um produto individual sob monitoramento.

Cada instância guarda os metadados de um produto (URL, loja, intervalo,
status) e serve como unidade atômica para o módulo de monitoramento.
Nenhuma lógica de scraping é incluída — apenas estrutura de dados e
mudanças de estado.

ProductWatcherManager — gerencia múltiplos ProductWatchers e integra
com o Scheduler para verificação periódica.
"""

from __future__ import annotations

import enum
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class WatcherStatus(enum.Enum):
    """Estados possíveis de um produto monitorado."""

    IDLE = "idle"
    ACTIVE = "active"
    PAUSED = "paused"
    ERROR = "error"
    STOPPED = "stopped"


@dataclass
class ProductWatcher:
    """
    Representa um único produto sendo monitorado.

    Attributes:
        product_id: Identificador único do produto.
        url: URL do produto na loja.
        store: Nome da loja (ex: "Amazon", "Mercado Livre").
        label: Rótulo amigável para exibição.
        interval_minutes: Intervalo mínimo entre verificações (minutos).
        status: Estado atual do watcher.
        last_check: Timestamp da última verificação realizada.
        next_check: Timestamp previsto para a próxima verificação.
        consecutive_errors: Contagem de erros consecutivos.
        max_errors: Limite de erros antes de pausar automaticamente.
        tags: Conjunto de tags para categorização futura.
    """

    product_id: str
    url: str
    store: str
    label: str = ""
    interval_minutes: int = 240
    status: WatcherStatus = WatcherStatus.IDLE
    last_check: Optional[datetime] = None
    next_check: Optional[datetime] = None
    consecutive_errors: int = 0
    max_errors: int = 5
    tags: set[str] = field(default_factory=set)

    # ── helpers de estado ──────────────────────────────────────────

    def is_due(self, reference: Optional[datetime] = None) -> bool:
        """
        Retorna True se o watcher estiver apto para ser verificado agora.

        Um watcher está "devido" quando:
        - Nunca foi verificado (last_check is None)
        - O tempo desde last_check ultrapassou interval_minutes
        """
        if self.status in (WatcherStatus.PAUSED, WatcherStatus.STOPPED):
            return False
        if self.last_check is None:
            return True
        ref = reference or datetime.now()
        elapsed = (ref - self.last_check).total_seconds() / 60.0
        return elapsed >= self.interval_minutes

    def mark_checked(self, timestamp: Optional[datetime] = None) -> None:
        """Registra uma verificação bem-sucedida e atualiza next_check."""
        now = timestamp or datetime.now()
        self.last_check = now
        self.next_check = datetime.fromtimestamp(
            now.timestamp() + self.interval_minutes * 60
        )
        self.consecutive_errors = 0
        self.status = WatcherStatus.ACTIVE

    def mark_error(self, timestamp: Optional[datetime] = None) -> None:
        """
        Registra um erro. Se consecutive_errors atingir max_errors,
        o watcher é automaticamente pausado.
        """
        self.consecutive_errors += 1
        if self.consecutive_errors >= self.max_errors:
            self.status = WatcherStatus.ERROR
        # mantém last_check para não re-verificar imediatamente
        self.last_check = timestamp or datetime.now()

    def pause(self) -> None:
        """Pausa o monitoramento deste produto."""
        self.status = WatcherStatus.PAUSED

    def resume(self) -> None:
        """Retoma o monitoramento, resetando erros."""
        self.status = WatcherStatus.ACTIVE
        self.consecutive_errors = 0

    def stop(self) -> None:
        """Interrompe permanentemente o monitoramento."""
        self.status = WatcherStatus.STOPPED

    @property
    def is_active(self) -> bool:
        """O watcher está em estado ativo (IDLE ou ACTIVE)."""
        return self.status in (WatcherStatus.IDLE, WatcherStatus.ACTIVE)

    @property
    def is_paused(self) -> bool:
        """O watcher está pausado."""
        return self.status == WatcherStatus.PAUSED

    # ── serialização ───────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Converte o watcher para dicionário (útil para persistência futura)."""
        return {
            "product_id": self.product_id,
            "url": self.url,
            "store": self.store,
            "label": self.label,
            "interval_minutes": self.interval_minutes,
            "status": self.status.value,
            "last_check": self.last_check.isoformat() if self.last_check else None,
            "next_check": self.next_check.isoformat() if self.next_check else None,
            "consecutive_errors": self.consecutive_errors,
            "max_errors": self.max_errors,
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, data: dict) -> ProductWatcher:
        """Reconstrói um watcher a partir de um dicionário."""
        return cls(
            product_id=data["product_id"],
            url=data["url"],
            store=data["store"],
            label=data.get("label", ""),
            interval_minutes=data.get("interval_minutes", 240),
            status=WatcherStatus(data.get("status", WatcherStatus.IDLE.value)),
            last_check=(
                datetime.fromisoformat(data["last_check"])
                if data.get("last_check")
                else None
            ),
            next_check=(
                datetime.fromisoformat(data["next_check"])
                if data.get("next_check")
                else None
            ),
            consecutive_errors=data.get("consecutive_errors", 0),
            max_errors=data.get("max_errors", 5),
            tags=set(data.get("tags", [])),
        )


class ProductWatcherManager:
    """
    Gerencia o registro, monitoramento e verificação periódica de produtos.

    Integra-se ao Scheduler para executar verificações em intervalos
    regulares sem bloquear a thread principal.

    Características:
        - Registro e remoção thread-safe de ProductWatchers.
        - Prevenção de registros duplicados (mesmo product_id).
        - Callback opcional acionado para cada produto "devido".
        - Início/parada segura do monitoramento.
        - Não executa callbacks após ser parado.
        - Logging de erros nas callbacks.
    """

    def __init__(
        self,
        scheduler: Optional[Scheduler] = None,
        on_check: Optional[Callable[[ProductWatcher], None]] = None,
        poll_interval_seconds: float = 60.0,
    ) -> None:
        """
        Args:
            scheduler: Instância de Scheduler a ser usada.
                Se None, cria uma nova internamente.
            on_check: Callable opcional invocada para cada produto
                que precisa ser verificado. Recebe o ProductWatcher.
            poll_interval_seconds: Intervalo do loop de verificação
                no Scheduler (segundos). Padrão 60s.
        """
        from src.monitor.scheduler import Scheduler  # lazy import to avoid circular dependency

        self._scheduler = scheduler or Scheduler()
        self._on_check = on_check
        self._poll_interval = poll_interval_seconds
        self._products: dict[str, ProductWatcher] = {}
        self._lock = threading.Lock()
        self._stopped = False

    # ── registro / remoção ──────────────────────────────────────────

    def register(self, product: ProductWatcher) -> None:
        """
        Registra um produto para monitoramento.

        Args:
            product: ProductWatcher a ser registrado.

        Raises:
            ValueError: Se o product_id já estiver registrado.
        """
        with self._lock:
            if product.product_id in self._products:
                raise ValueError(
                    f"Produto '{product.product_id}' já está registrado."
                )
            self._products[product.product_id] = product

    def remove(self, product_id: str) -> Optional[ProductWatcher]:
        """
        Remove um produto pelo identificador.

        Args:
            product_id: ID do produto a remover.

        Returns:
            O ProductWatcher removido, ou None se não encontrado.
        """
        with self._lock:
            return self._products.pop(product_id, None)

    def get(self, product_id: str) -> Optional[ProductWatcher]:
        """Retorna um produto pelo ID, sem removê-lo."""
        with self._lock:
            return self._products.get(product_id)

    def list_all(self) -> list[ProductWatcher]:
        """Retorna uma cópia da lista de todos os produtos registrados."""
        with self._lock:
            return list(self._products.values())

    # ── propriedades ────────────────────────────────────────────────

    @property
    def count(self) -> int:
        """Número de produtos registrados."""
        with self._lock:
            return len(self._products)

    @property
    def is_running(self) -> bool:
        """Indica se o monitoramento está em execução."""
        return self._scheduler.is_running

    @property
    def products(self) -> list[ProductWatcher]:
        """Lista de todos os produtos registrados (atalho para list_all)."""
        return self.list_all()

    # ── ciclo de vida ───────────────────────────────────────────────

    def start(self) -> None:
        """
        Inicia o monitoramento periódico dos produtos registrados.

        Cria uma tarefa no Scheduler que verifica periodicamente
        quais produtos estão "devidos" e chama o on_check para cada um.
        A execução ocorre em thread daemon (não bloqueia a main thread).
        """
        self._stopped = False

        # Registra a task de verificação no scheduler
        self._scheduler.register(
            task_id="product_watcher_check",
            callback=self._check_due_products,
            interval_seconds=self._poll_interval,
        )
        self._scheduler.start()

    def stop(self, wait: bool = True) -> None:
        """
        Para o monitoramento de forma segura.

        Após parar, nenhum callback será executado mesmo que
        produtos estejam devidos.

        Args:
            wait: Se True, aguarda a thread do scheduler finalizar.
        """
        self._stopped = True
        if self._scheduler.is_running:
            self._scheduler.stop(wait=wait)
        # Remove a task do scheduler para permitir re-registro
        if self._scheduler.task_exists("product_watcher_check"):
            self._scheduler.remove("product_watcher_check")

    # ── lógica interna ──────────────────────────────────────────────

    def _check_due_products(self) -> None:
        """
        Verifica quais produtos estão "devidos" e chama on_check.

        Esta é a callback registrada no Scheduler. É chamada
        periodicamente no intervalo configurado.

        Se o manager foi parado (stopped), não executa nada.
        Erros nas callbacks são logados, nunca propagados.
        """
        if self._stopped:
            return

        due: list[ProductWatcher] = []
        with self._lock:
            for product in self._products.values():
                if product.is_due():
                    due.append(product)

        for product in due:
            try:
                if self._on_check is not None:
                    self._on_check(product)
            except Exception as exc:
                logger.error(
                    "Erro ao verificar produto '%s': %s",
                    product.product_id,
                    exc,
                )

    def __repr__(self) -> str:
        return (
            f"<ProductWatcherManager"
            f" products={self.count}"
            f" running={self.is_running}>"
        )