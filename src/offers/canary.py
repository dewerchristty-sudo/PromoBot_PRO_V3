from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import time
from uuid import uuid4

from .activation import OfferActivationFlags
from .identity import OfferIdentity
from src.stores.active import is_active_store


@dataclass(frozen=True, slots=True)
class CanaryOfferDecision:
    alert: object
    audit_id: str
    identity: str
    title: str
    store: str
    category: str
    score: float
    scheduler: str
    legacy_decision: str
    intelligent_decision: str
    difference: str
    reason: str
    decision_ms: float


class OfferCanaryController:
    """Roteia ofertas; o transporte continua pertencendo ao Notifier legado."""

    def __init__(
        self, repository, flags=None, clock=None, auto_stop_callback=None
    ):
        self.repository = repository
        self.flags = flags or OfferActivationFlags.from_environment()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.auto_stop_callback = auto_stop_callback

    def execute(self, alerts, legacy_send):
        alerts = [
            alert for alert in alerts or ()
            if is_active_store(self.value(alert, "loja", "store"))
        ]
        if not alerts:
            return "Nenhum alerta disparado."
        flags = self.flags
        if (
            not flags.intelligent_scheduler_enabled
            or flags.canary_percent <= 0
        ):
            return legacy_send(alerts)

        started = time.perf_counter()
        try:
            decisions = self.decide(alerts)
        except Exception as error:
            reason = f"{type(error).__name__}: {error}"
            if not flags.enable_rollback:
                return f"Falha ao enviar: ativacao inteligente: {reason}"
            result = legacy_send(alerts)
            self.record_rollback(alerts, result, reason, started)
            return result

        selected = [
            item.alert for item in decisions
            if (
                item.scheduler == "legacy"
                and item.legacy_decision == "enviar"
            )
            or (
                item.scheduler == "inteligente"
                and item.intelligent_decision == "enviar"
            )
        ]
        if flags.dry_run_transport:
            result = "simulated_send"
        elif not selected:
            result = "Nenhum envio: Scheduler inteligente sem oferta elegível."
        else:
            try:
                result = legacy_send(selected)
            except Exception as error:
                reason = f"{type(error).__name__}: {error}"
                self.record_rollback(
                    selected,
                    f"Falha ao enviar: {reason}",
                    f"falha_transporte_sem_reenvio: {reason}",
                    started,
                )
                return f"Falha ao enviar: {reason}"
        try:
            self.audit(decisions, result, rollback_reason="")
        except Exception as error:
            if flags.stop_on_audit_failure and self.auto_stop_callback:
                self.auto_stop_callback(
                    f"Falha de auditoria: {type(error).__name__}: {error}",
                    {"audit_failure": 1},
                )
            # O transporte não pode ser repetido após possível entrega parcial.
            pass
        return result

    def decide(self, alerts):
        decisions = []
        seen = set()
        now = self.clock()
        limits = self.repository.canary_send_counts(now)
        intelligent_hour = limits["hour"]
        intelligent_day = limits["day"]

        for alert in alerts:
            started = time.perf_counter()
            title = self.value(alert, "titulo", "title")
            store = self.value(alert, "loja", "store")
            category = self.value(alert, "categoria", "category")
            link = self.value(alert, "link", "product_link")
            identity = self.identity(title, store, link)
            bucket = self.bucket(identity)
            use_intelligent = bucket < self.flags.canary_percent
            analysis = self.repository.latest_offer_analysis(
                title, store, identity
            )
            score = float(analysis["score"] if analysis else 0)
            approved = bool(analysis and analysis["filter_approved"])
            duplicate = bool(
                analysis and analysis["duplicate_type"] not in (
                    "", "novo_produto", "nova_promocao"
                )
            )
            already_sent = (
                identity in seen
                or self.repository.canary_identity_was_sent(identity)
            )
            intelligent = "enviar"
            reason = "score_e_filtros_aprovados"
            if not analysis:
                intelligent, reason = "aguardar", "analise_inteligente_ausente"
            elif score < self.flags.minimum_score_to_send:
                intelligent, reason = "aguardar", "score_insuficiente"
            elif not approved:
                intelligent, reason = "aguardar", "filtro_reprovado"
            elif duplicate or already_sent:
                intelligent, reason = "aguardar", "duplicidade"
            elif intelligent_hour >= self.flags.max_send_per_hour:
                intelligent, reason = "aguardar", "limite_por_hora"
            elif intelligent_day >= self.flags.max_send_per_day:
                intelligent, reason = "aguardar", "limite_diario"

            scheduler = "inteligente" if use_intelligent else "legado"
            if scheduler == "inteligente" and intelligent == "enviar":
                intelligent_hour += 1
                intelligent_day += 1
                seen.add(identity)
            legacy = "aguardar" if already_sent else "enviar"
            if scheduler == "legado" and legacy == "enviar":
                seen.add(identity)
            difference = (
                "sim" if legacy != intelligent else "nao"
            ) if self.flags.compare_with_legacy else "comparacao_desligada"
            decisions.append(CanaryOfferDecision(
                alert=alert,
                audit_id=uuid4().hex,
                identity=identity,
                title=title,
                store=store,
                category=category,
                score=score,
                scheduler=scheduler,
                legacy_decision=legacy,
                intelligent_decision=intelligent,
                difference=difference,
                reason=reason if use_intelligent else "fora_da_amostra_canary",
                decision_ms=round((time.perf_counter() - started) * 1000, 3),
            ))
        return tuple(decisions)

    def audit(self, decisions, result, rollback_reason):
        success = str(result).startswith("Enviado por:")
        rows = []
        for item in decisions:
            item_data = {
                name: getattr(item, name)
                for name in item.__dataclass_fields__
            }
            actually_selected = (
                (
                    item.scheduler == "legacy"
                    and item.legacy_decision == "enviar"
                )
                or (
                    item.scheduler == "inteligente"
                    and item.intelligent_decision == "enviar"
                )
            )
            rows.append({
                **item_data,
                "result": result,
                "sent": bool(success and actually_selected),
                "rollback_reason": rollback_reason,
                "flags_json": json.dumps(
                    self.flags.as_dict(), ensure_ascii=False
                ),
                "canary_percent": self.flags.canary_percent,
                "created_at": self.clock(),
            })
        self.repository.record_canary_decisions(rows)

    def record_rollback(self, alerts, result, reason, started):
        decisions = []
        elapsed = round((time.perf_counter() - started) * 1000, 3)
        for alert in alerts:
            title = self.value(alert, "titulo", "title")
            store = self.value(alert, "loja", "store")
            link = self.value(alert, "link", "product_link")
            decisions.append(CanaryOfferDecision(
                alert=alert,
                audit_id=uuid4().hex,
                identity=self.identity(title, store, link),
                title=title,
                store=store,
                category=self.value(alert, "categoria", "category"),
                score=0,
                scheduler="legado_rollback",
                legacy_decision="enviar",
                intelligent_decision="erro",
                difference="sim",
                reason="rollback_automatico",
                decision_ms=elapsed,
            ))
        try:
            self.audit(decisions, result, rollback_reason=reason)
        except Exception:
            pass

    @staticmethod
    def bucket(identity):
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        return int(digest[:8], 16) % 100

    @staticmethod
    def identity(title, store, link):
        canonical = OfferIdentity().canonicalize_link(link)
        text = f"{store}|{title}|{canonical}"
        return hashlib.sha256(text.casefold().encode("utf-8")).hexdigest()

    @staticmethod
    def value(alert, *names):
        for name in names:
            if isinstance(alert, dict) and alert.get(name) not in (None, ""):
                return str(alert[name])
            value = getattr(alert, name, None)
            if value not in (None, ""):
                return str(value)
        return ""
