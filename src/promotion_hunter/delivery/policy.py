from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

OPERATIONAL_TIMEZONE = ZoneInfo("America/Sao_Paulo")


@dataclass(frozen=True)
class DeliveryPolicyDecision:
    allowed: bool
    reason: str


@dataclass(frozen=True)
class DeliveryPolicy:
    max_products_per_keyword: int = 5
    max_messages_per_run: int = 3
    max_messages_per_hour: int = 5
    max_messages_per_session: int = 10
    minimum_interval_minutes: int = 10
    minimum_interval_seconds: int | None = None
    duplicate_window_hours: int = 24
    allowed_start: time = time(8, 0)
    allowed_end: time = time(22, 0)

    def within_window(self, now):
        if now.tzinfo is None:
            raise ValueError(
                "DeliveryPolicy.within_window() recebeu datetime naive. "
                "Forneça um datetime com timezone (ex: UTC)."
            )
        local = now.astimezone(OPERATIONAL_TIMEZONE)
        current = local.time().replace(tzinfo=None)
        return self.allowed_start <= current < self.allowed_end

    def evaluate(self, *, mode, live_enabled, destination, now,
                 run_sent, hour_sent, session_sent, last_sent_at):
        if mode != "live":
            return DeliveryPolicyDecision(False, f"modo_{mode}")
        if not live_enabled:
            return DeliveryPolicyDecision(False, "trava_live_desativada")
        if not destination:
            return DeliveryPolicyDecision(False, "destino_pessoal_ausente")
        if not self.within_window(now):
            return DeliveryPolicyDecision(False, "fora_do_horario")
        if run_sent >= self.max_messages_per_run:
            return DeliveryPolicyDecision(False, "limite_execucao")
        accelerated = (
            self.max_messages_per_run == 10
            and self.minimum_interval_seconds == 3
        )
        hour_limit = (
            max(self.max_messages_per_hour, self.max_messages_per_run)
            if accelerated else self.max_messages_per_hour
        )
        session_limit = (
            max(self.max_messages_per_session, self.max_messages_per_run)
            if accelerated else self.max_messages_per_session
        )
        if hour_sent >= hour_limit:
            return DeliveryPolicyDecision(False, "limite_hora")
        if session_sent >= session_limit:
            return DeliveryPolicyDecision(False, "limite_sessao")
        if last_sent_at:
            last = datetime.fromisoformat(last_sent_at)
            interval = (
                timedelta(seconds=self.minimum_interval_seconds)
                if self.minimum_interval_seconds is not None
                else timedelta(minutes=self.minimum_interval_minutes)
            )
            if now - last < interval:
                return DeliveryPolicyDecision(False, "intervalo_minimo")
        return DeliveryPolicyDecision(True, "permitido")
