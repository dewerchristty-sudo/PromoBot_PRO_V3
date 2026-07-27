from datetime import datetime, timedelta, timezone
from uuid import uuid4

from .models import PilotAuthorization, PilotDecision
from .validation import validate_pilot_config


CONFIRMATION_PHRASE = "AUTORIZO UM ENVIO PILOTO SUPERVISIONADO"


class PilotManager:

    def __init__(self, config, sent_history=None, clock=None):
        self.config = config
        self.sent_history = list(sent_history or [])
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.authorizations = {}
        self.audit = []
        self.auto_stopped = False

    def evaluate(self, product, dry_run=True):
        audit = [
            f"operationally_ready={product.operationally_ready}",
            f"approved={product.approved}",
            f"selected={product.selected}",
            f"score={product.score}",
            f"threshold={product.threshold}",
        ]
        if self.auto_stopped:
            return self.decision(product, "AUTO_STOPPED", audit, True)
        if not product.affiliate_url or not product.affiliate_valid:
            return self.decision(product, "AFFILIATE_LINK_REQUIRED", audit)
        if not product.operationally_ready:
            return self.decision(product, "NOT_OPERATIONALLY_READY", audit)
        if product.score < product.threshold:
            return self.decision(product, "SCORE_BELOW_THRESHOLD", audit)
        if not product.approved:
            return self.decision(product, "NOT_APPROVED", audit)
        if not product.selected:
            return self.decision(product, "NOT_SELECTED", audit)
        status = validate_pilot_config(self.config, product.threshold)
        if status.state == "DISABLED":
            return self.decision(product, "PILOT_DISABLED", audit)
        if not status.valid:
            return self.decision(
                product, "PILOT_CONFIGURATION_REQUIRED", audit
            )
        if product.store.casefold() not in {
            store.casefold() for store in self.config.allowed_stores
        }:
            return self.decision(product, "STORE_NOT_ALLOWED", audit)
        if len(self.sent_history) >= self.config.max_messages:
            return self.decision(product, "MESSAGE_LIMIT_REACHED", audit)
        if self.in_cooldown():
            return self.decision(product, "COOLDOWN_ACTIVE", audit)
        if self.config.require_manual_confirmation:
            return PilotDecision(
                state="DRY_RUN" if dry_run else "AWAITING_CONFIRMATION",
                operationally_ready=True, approved=True, selected=True,
                authorized=False, sent=False,
                reason="MANUAL_CONFIRMATION_REQUIRED",
                audit=tuple(audit),
            )
        return self.decision(
            product, "MANUAL_CONFIRMATION_REQUIRED", audit
        )

    def decision(self, product, reason, audit, auto_stopped=False):
        state = "AUTO_STOPPED" if auto_stopped else (
            "DRY_RUN" if reason in {
                "SCORE_BELOW_THRESHOLD", "NOT_SELECTED",
                "NOT_OPERATIONALLY_READY", "AFFILIATE_LINK_REQUIRED",
            } else "FAILED"
        )
        return PilotDecision(
            state=state,
            operationally_ready=product.operationally_ready,
            approved=product.approved,
            selected=product.selected,
            authorized=False, sent=False, reason=reason,
            transport_called=False, auto_stopped=auto_stopped,
            audit=tuple(audit),
        )

    def authorize(self, product, phrase):
        decision = self.evaluate(product, dry_run=False)
        if decision.state != "AWAITING_CONFIRMATION":
            return None, decision
        if phrase != CONFIRMATION_PHRASE:
            return None, self.decision(
                product, "CONFIRMATION_PHRASE_INVALID", decision.audit
            )
        now = self.clock()
        authorization = PilotAuthorization(
            authorization_id=uuid4().hex,
            product_identity=product.identity,
            created_at=now,
            expires_at=now + timedelta(
                seconds=self.config.authorization_timeout_seconds
            ),
        )
        self.authorizations[authorization.authorization_id] = authorization
        self.audit.append(("AUTHORIZED", product.identity, now.isoformat()))
        return authorization, PilotDecision(
            state="AUTHORIZED", operationally_ready=True,
            approved=True, selected=True, authorized=True, sent=False,
            reason="EXPLICIT_CONFIRMATION_ACCEPTED",
        )

    def consume_authorization(self, authorization_id):
        authorization = self.authorizations.get(authorization_id)
        if not authorization or authorization.consumed:
            return False, "AUTHORIZATION_INVALID_OR_REUSED"
        if self.clock() >= authorization.expires_at:
            authorization.state = "FAILED"
            return False, "AUTHORIZATION_EXPIRED"
        authorization.consumed = True
        return True, "AUTHORIZATION_CONSUMED"

    def in_cooldown(self):
        if not self.sent_history or self.config.cooldown_minutes <= 0:
            return False
        latest = max(self.sent_history)
        return self.clock() < latest + timedelta(
            minutes=self.config.cooldown_minutes
        )

    def record_error(self, reason):
        self.audit.append(("ERROR", reason, self.clock().isoformat()))
        if self.config.auto_stop_on_error:
            self.auto_stopped = True
