from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from uuid import uuid4

from .activation import OfferActivationFlags


SAFE_CONFIRMATION = "CONFIRMO A ATIVAÇÃO DO CANARY"


@dataclass(frozen=True, slots=True)
class ActivationProfile:
    name: str
    canary_percent: int
    minimum_score: float
    max_per_hour: int
    max_per_day: int
    dry_run: bool

    def flags(self):
        return OfferActivationFlags(
            intelligent_scheduler_enabled=True,
            compare_with_legacy=True,
            canary_percent=self.canary_percent,
            minimum_score_to_send=self.minimum_score,
            max_send_per_hour=self.max_per_hour,
            max_send_per_day=self.max_per_day,
            enable_rollback=True,
            dry_run_transport=self.dry_run,
        )


CANARY_SAFE_5_PERCENT = ActivationProfile(
    "CANARY_SAFE_5_PERCENT", 5, 90, 1, 3, True
)

ACTIVATION_STAGES = (
    ActivationProfile("LEGACY", 0, 90, 1, 3, False),
    CANARY_SAFE_5_PERCENT,
    replace(CANARY_SAFE_5_PERCENT, name="CANARY_REAL_5", dry_run=False),
    ActivationProfile("CANARY_10", 10, 90, 1, 3, False),
    ActivationProfile("CANARY_25", 25, 90, 1, 3, False),
    ActivationProfile("CANARY_50", 50, 90, 2, 6, False),
    ActivationProfile("CANARY_75", 75, 90, 3, 9, False),
    ActivationProfile("CANARY_100", 100, 90, 3, 12, False),
)


@dataclass(frozen=True, slots=True)
class ActivationCheck:
    name: str
    passed: bool
    detail: str
    critical: bool = True


class OfferPreflight:
    REQUIRED_TABLES = {
        "offer_queue", "offer_pipeline_items", "offer_canary_decisions",
        "offer_activation_sessions", "offer_activation_checks",
        "offer_activation_events", "offer_canary_auto_stops",
    }

    def __init__(
        self, repository, notifier_available=None, monitor_available=None
    ):
        self.repository = repository
        self.notifier_available = (
            self.component_available("src.core.notifier", "Notifier", "send_alerts")
            if notifier_available is None else bool(notifier_available)
        )
        self.monitor_available = (
            self.component_available(
                "src.core.monitor", "MonitorRunner", "send_automatic_alerts"
            )
            if monitor_available is None else bool(monitor_available)
        )

    def run(self, flags):
        tables = self.repository.table_names()
        health = self.repository.activation_health()
        checks = (
            ActivationCheck("shadow_database", True, "Banco shadow acessível."),
            ActivationCheck(
                "migrations", self.REQUIRED_TABLES <= tables,
                "Migrações e tabelas obrigatórias aplicadas."
            ),
            ActivationCheck("notifier", self.notifier_available, "Notifier disponível."),
            ActivationCheck("monitor", self.monitor_available, "Monitor disponível."),
            ActivationCheck(
                "critical_errors", health["critical_errors"] == 0,
                f"Erros críticos recentes: {health['critical_errors']}."
            ),
            ActivationCheck(
                "repeated_rollbacks", health["recent_rollbacks"] <= 2,
                f"Rollbacks na última hora: {health['recent_rollbacks']}."
            ),
            ActivationCheck(
                "reservations", health["invalid_reservations"] == 0,
                f"Reservas inconsistentes: {health['invalid_reservations']}."
            ),
            ActivationCheck(
                "duplicates", health["pending_duplicates"] == 0,
                f"Duplicidades pendentes: {health['pending_duplicates']}."
            ),
            ActivationCheck(
                "canary_percent", 0 <= flags.canary_percent <= 100,
                f"Canary: {flags.canary_percent}%."
            ),
            ActivationCheck(
                "hour_limit", flags.max_send_per_hour > 0,
                f"Limite/hora: {flags.max_send_per_hour}."
            ),
            ActivationCheck(
                "day_limit",
                flags.max_send_per_day >= flags.max_send_per_hour,
                f"Limite/dia: {flags.max_send_per_day}."
            ),
            ActivationCheck(
                "minimum_score", 0 <= flags.minimum_score_to_send <= 100,
                f"Score mínimo: {flags.minimum_score_to_send}."
            ),
            ActivationCheck(
                "rollback", flags.enable_rollback,
                "Rollback obrigatório para ativação."
            ),
        )
        return checks

    @staticmethod
    def component_available(module_name, class_name, method_name):
        try:
            module = __import__(module_name, fromlist=[class_name])
            component = getattr(module, class_name)
            return callable(getattr(component, method_name, None))
        except Exception:
            return False


class OfferActivationManager:
    def __init__(self, repository, config_path=None, clock=None):
        self.repository = repository
        self.config_path = Path(config_path or os.getenv(
            "OFFER_ACTIVATION_CONFIG_PATH", "offer_activation.json"
        ))
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def activate(self, profile, actor, confirmation, real_transport=False):
        flags = profile.flags()
        if real_transport:
            flags = replace(flags, dry_run_transport=False)
            if confirmation != SAFE_CONFIRMATION:
                raise PermissionError("Confirmação forte inválida.")
        elif confirmation != "CONFIRMO DRY RUN":
            raise PermissionError("Confirmação de Dry Run inválida.")
        session_id = uuid4().hex
        checks = OfferPreflight(self.repository).run(flags)
        self.repository.record_activation_checks(session_id, checks)
        failed = [item for item in checks if item.critical and not item.passed]
        if failed:
            self.repository.record_activation_event(
                session_id, "activation_blocked", actor,
                "; ".join(item.name for item in failed), {}, flags.as_dict()
            )
            raise RuntimeError("Ativação bloqueada: " + ", ".join(
                item.detail for item in failed
            ))
        before = OfferActivationFlags.from_environment().as_dict()
        self.write_config(flags)
        status = "active" if real_transport else "dry_run"
        self.repository.create_activation_session(
            session_id, status, actor, not real_transport, flags.as_dict(),
            self.stage_for(flags), self.clock()
        )
        self.repository.record_activation_event(
            session_id, "activated", actor, profile.name,
            before, flags.as_dict()
        )
        return session_id

    def deactivate(self, actor, reason, status="manually_stopped"):
        before = OfferActivationFlags.from_environment().as_dict()
        stopped = replace(
            OfferActivationFlags.from_environment(),
            intelligent_scheduler_enabled=False,
            canary_percent=0,
            dry_run_transport=False,
        )
        self.write_config(stopped)
        session = self.repository.current_activation_session()
        session_id = session["id"] if session else ""
        self.repository.finish_activation_session(
            session_id, status, reason, self.clock()
        )
        self.repository.record_activation_event(
            session_id, "deactivated", actor, reason,
            before, stopped.as_dict()
        )
        return stopped

    def auto_stop(self, reason, metrics):
        stopped = self.deactivate("system", reason, "auto_stopped")
        session = self.repository.latest_activation_session()
        self.repository.record_auto_stop(
            session["id"] if session else "", reason, metrics, self.clock()
        )
        return stopped

    def write_config(self, flags):
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.config_path.with_suffix(self.config_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(flags.as_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.config_path)

    @staticmethod
    def stage_for(flags):
        eligible = [
            index for index, profile in enumerate(ACTIVATION_STAGES)
            if profile.canary_percent <= flags.canary_percent
        ]
        return max(eligible or [0])
