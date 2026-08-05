"""Read-only safety gate for starting the Promotion Hunter in LIVE mode."""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from src.affiliates.amazon import validate_associate_tag
from src.affiliates.config import runtime_env_path
from src.core.whatsapp_control import WhatsAppControl

from .config import OPERATIONAL_TIMEZONE, operational_settings
from .process_lock import HunterProcessLock


CATEGORY_GROUP_KEYS = (
    "WHATSAPP_GROUP_MAMAE_BEBE",
    "WHATSAPP_GROUP_CASA_ENXOVAL",
    "WHATSAPP_GROUP_ELETRODOMESTICOS",
    "WHATSAPP_GROUP_SMARTPHONES_TECNOLOGIA",
    "WHATSAPP_GROUP_BELEZA_PERFUMARIA",
    "WHATSAPP_GROUP_LIMPEZA_UTILIDADES",
)


@dataclass(frozen=True, slots=True)
class LivePreflightResult:
    allowed: bool
    errors: tuple[str, ...]
    details: dict


class LiveStartPreflight:
    """Validates LIVE without changing environment, databases or queues."""

    def __init__(self, database_path="promotion_hunter.db",
                 app_database_path="promobot.db", whatsapp=None, clock=None,
                 lock_checker=None):
        self.database_path = Path(database_path)
        self.app_database_path = Path(app_database_path)
        self.whatsapp = whatsapp or WhatsAppControl()
        self.clock = clock or (lambda: datetime.now(OPERATIONAL_TIMEZONE))
        self.lock_checker = lock_checker or HunterProcessLock.is_locked

    @staticmethod
    def _true(name):
        return os.getenv(name, "false").strip().casefold() in {
            "1", "true", "yes", "on", "sim",
        }

    @staticmethod
    def _readonly(path):
        return sqlite3.connect(
            f"file:{Path(path).resolve().as_posix()}?mode=ro", uri=True
        )

    def run(self, *, controller_running=False):
        errors = []
        env_path = runtime_env_path()
        if not env_path.is_file():
            errors.append(f"Arquivo .env externo ausente: {env_path}")
        if not self._true("PROMOTION_HUNTER_LIVE_DELIVERY"):
            errors.append("PROMOTION_HUNTER_LIVE_DELIVERY precisa estar true.")
        if not self._true("PROMOTION_HUNTER_REAL_SEND_AUTHORIZED"):
            errors.append(
                "PROMOTION_HUNTER_REAL_SEND_AUTHORIZED precisa estar true."
            )
        if controller_running:
            errors.append("Ja existe um scheduler do Hunter ativo na interface.")
        try:
            if self.lock_checker():
                errors.append("Mutex do Promotion Hunter esta ocupado.")
        except Exception as exc:
            errors.append(f"Nao foi possivel validar o mutex: {exc}")

        pending = 0
        scheduler_running = False
        pending_session = 0
        pending_backlog = 0
        try:
            with self._readonly(self.database_path) as connection:
                integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
                if str(integrity).casefold() != "ok":
                    errors.append(f"Banco do Hunter inconsistente: {integrity}")
                row = connection.execute(
                    "SELECT running FROM promotion_hunter_scheduler_state "
                    "WHERE singleton_id=1"
                ).fetchone()
                scheduler_running = bool(row and row[0])
                pending = connection.execute(
                    "SELECT COUNT(*) FROM promotion_hunter_delivery_queue "
                    "WHERE status IN ('pending','failed','sending')"
                ).fetchone()[0]
                # Sessao atual: itens aprovados nas ultimas 24h
                pending_session = connection.execute(
                    "SELECT COUNT(*) FROM promotion_hunter_delivery_queue "
                    "WHERE status IN ('pending','failed','sending') "
                    "AND approved_at >= datetime('now', '-24 hours')"
                ).fetchone()[0]
                pending_backlog = max(pending - pending_session, 0)
        except (sqlite3.Error, OSError) as exc:
            errors.append(f"Falha ao validar banco do Hunter: {exc}")
        if scheduler_running:
            errors.append("Scheduler persistido ainda esta marcado como ativo.")
        if pending_backlog > 0:
            # Backlog antigo NAO bloqueia o LIVE. Apenas informa o operador.
            # O scheduler processara apenas itens da sessao atual.
            pass  # reported via details dict, not as blocking error

        now = self.clock().astimezone(OPERATIONAL_TIMEZONE)
        if not 8 <= now.hour < 22:
            errors.append("Fora da janela operacional permitida (08:00-22:00).")
        settings = operational_settings(self.app_database_path)
        if settings.accelerated:
            errors.append("Modo acelerado deve estar desligado no primeiro LIVE.")
        if settings.max_messages_per_run < 1:
            errors.append("Limite por ciclo invalido.")
        if settings.min_seconds_between_messages <= 0:
            errors.append("Intervalo entre mensagens invalido.")

        groups = {
            key: os.getenv(key, "").strip() for key in CATEGORY_GROUP_KEYS
            if os.getenv(key, "").strip()
        }
        if not groups:
            errors.append("Nenhum grupo de categoria esta configurado.")
        invalid_groups = [key for key, value in groups.items()
                          if not value.endswith("@g.us")]
        if invalid_groups:
            errors.append("Grupo de categoria invalido: " + ", ".join(invalid_groups))
        review = os.getenv("WHATSAPP_REVIEW_GROUP", "").strip()
        if review and review in groups.values():
            errors.append("Grupo Review nao pode participar do roteamento automatico.")
        blocked = os.getenv("PROMOTION_HUNTER_BLOCKED_GROUP", "").strip()
        if blocked and blocked in groups.values():
            errors.append("Grupo bloqueado esta configurado como destino automatico.")

        try:
            validate_associate_tag(os.getenv("AMAZON_ASSOCIATE_TAG", ""))
        except ValueError as exc:
            errors.append(str(exc))
        state = "unknown"
        try:
            state = self.whatsapp.connection_state()
            if state not in {"open", "connected", "online"}:
                errors.append(f"WhatsApp nao esta open: estado={state}.")
        except Exception as exc:
            errors.append(f"Evolution API indisponivel: {exc}")

        return LivePreflightResult(not errors, tuple(errors), {
            "env_path": str(env_path),
            "whatsapp_state": state,
            "destinations": tuple(groups.values()),
            "stores": ("Amazon",),
            "max_per_cycle": 1,
            "max_per_session": 2,
            "minimum_interval_seconds": max(
                settings.min_seconds_between_messages, 600
            ),
            "review": review,
            "blocked_group": blocked,
            "pending_total": int(pending),
            "pending_session": int(pending_session),
            "pending_backlog": int(pending_backlog),
            "accelerated": bool(settings.accelerated),
            "started_at": now.isoformat(),
        })
