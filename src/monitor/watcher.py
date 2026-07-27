"""
ProductWatcher — representa um produto individual sob monitoramento.

Cada instância guarda os metadados de um produto (URL, loja, intervalo,
status) e serve como unidade atômica para o módulo de monitoramento.
Nenhuma lógica de scraping é incluída — apenas estrutura de dados e
mudanças de estado.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


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