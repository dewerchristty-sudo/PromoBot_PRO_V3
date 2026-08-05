from datetime import datetime, timedelta, timezone
from uuid import uuid4

from src.database.offer_repository import OfferRepository

from .models import QueueOffer, RankedOffer
from .policy import OfferSchedulerPolicy
from .score import OfferScore


class OfferQueue:
    """Fila persistente com máquina de estados explícita."""

    VALID_TRANSITIONS = {
        "queued": {
            "blocked", "reserved", "expired", "discarded",
            "failed", "cancelled",
        },
        "blocked": {"queued", "expired", "discarded", "cancelled"},
        "reserved": {
            "queued", "selected_shadow", "expired", "failed", "cancelled",
        },
        "selected_shadow": {"sent", "cancelled"},
        "failed": {"queued", "discarded", "cancelled"},
        "sent": set(),
        "expired": set(),
        "discarded": set(),
        "cancelled": set(),
    }

    def __init__(
        self,
        repository: OfferRepository,
        policy: OfferSchedulerPolicy | None = None,
    ):
        self.repository = repository
        self.policy = policy or OfferSchedulerPolicy()

    def enqueue_ranked(
        self,
        ranked: RankedOffer,
        operational_blocks=(),
        available_at: datetime | None = None,
        expires_at: datetime | None = None,
        evaluation_id: str | None = None,
    ) -> tuple[QueueOffer, bool]:
        now = self.now()
        current = OfferScore.number(ranked.candidate.current_price)
        # Preço anterior explícito tem prioridade; histórico só vale se > preço atual
        raw_previous = None
        explicit = ranked.candidate.previous_price
        if explicit is not None and OfferScore.number(explicit) > current:
            raw_previous = explicit
        elif (
            ranked.candidate.historical_reference_price is not None
            and OfferScore.number(ranked.candidate.historical_reference_price) > current
        ):
            raw_previous = ranked.candidate.historical_reference_price
        previous = (
            OfferScore.number(raw_previous) if raw_previous is not None else 0.0
        )
        discount = (
            OfferScore.discount_percent(current, previous)
            if previous > 0
            else 0.0
        )
        blocks = tuple(str(item) for item in operational_blocks if str(item))
        status = "blocked" if blocks else "queued"
        offer = QueueOffer(
            id=None,
            evaluation_id=evaluation_id or uuid4().hex,
            product_id=str(ranked.candidate.product_id or ""),
            canonical_identity=ranked.identity.signature,
            promotion_signature=ranked.identity.promotion_signature,
            title=ranked.candidate.title,
            store=ranked.candidate.store,
            category=ranked.candidate.category,
            current_price=current,
            previous_price=previous,
            discount_percent=discount,
            saving_amount=max(previous - current, 0.0),
            score=ranked.score.total,
            classification=ranked.score.classification,
            confidence=ranked.score.confidence,
            score_components=ranked.score.components,
            status=status,
            priority=self.priority(ranked),
            available_at=available_at or now,
            expires_at=expires_at or (
                now + timedelta(hours=self.policy.default_expiration_hours)
            ),
            blocked_reason="; ".join(blocks),
            blocked_at=now if blocks else None,
            created_at=now,
            updated_at=now,
        )
        persisted, created = self.repository.enqueue(offer)
        if created:
            return persisted, True

        # Uma nova avaliação pode resolver (ou introduzir) bloqueios
        # operacionais sem apagar o histórico da oferta.
        if persisted.status == "blocked" and status == "queued":
            persisted = self.unblock(
                persisted.id,
                "Prontidao operacional reavaliada e liberada.",
            )
        elif persisted.status == "queued" and status == "blocked":
            persisted = self.block(persisted.id, offer.blocked_reason)
        elif persisted.status == "blocked" and status == "blocked":
            persisted = self.repository.transition(
                persisted.id,
                ("blocked",),
                "blocked",
                "Bloqueios operacionais reavaliados.",
                fields={
                    "blocked_reason": offer.blocked_reason,
                    "blocked_at": now,
                },
            )
        return persisted, False

    def transition(
        self,
        item_id: int,
        new_status: str,
        reason: str = "",
        run_id: str = "",
        fields: dict | None = None,
    ) -> QueueOffer:
        item = self.repository.get(item_id)
        if not item:
            raise KeyError(f"Oferta {item_id} não encontrada.")
        allowed = self.VALID_TRANSITIONS.get(item.status, set())
        if new_status not in allowed:
            raise ValueError(
                f"Transição inválida: {item.status} -> {new_status}."
            )
        return self.repository.transition(
            item_id,
            (item.status,),
            new_status,
            reason,
            run_id,
            fields,
        )

    def update_priority(self, item_id: int, priority: float) -> QueueOffer:
        item = self.repository.get(item_id)
        if not item:
            raise KeyError(f"Oferta {item_id} não encontrada.")
        return self.repository.transition(
            item_id,
            (item.status,),
            item.status,
            "Prioridade atualizada.",
            fields={"priority": float(priority)},
        )

    def block(self, item_id: int, reason: str) -> QueueOffer:
        return self.transition(
            item_id,
            "blocked",
            reason,
            fields={
                "blocked_reason": reason,
                "blocked_at": self.now(),
            },
        )

    def unblock(self, item_id: int, reason="Bloqueio corrigido.") -> QueueOffer:
        return self.transition(
            item_id,
            "queued",
            reason,
            fields={"blocked_reason": "", "blocked_at": None},
        )

    def discard(self, item_id: int, reason: str) -> QueueOffer:
        return self.transition(item_id, "discarded", reason)

    def fail(self, item_id: int, error: str) -> QueueOffer:
        return self.transition(
            item_id,
            "failed",
            error,
            fields={"last_error": str(error)},
        )

    def select_shadow(
        self,
        item_id: int,
        run_id: str,
        reason="Selecionada pelo scheduler em modo sombra.",
    ) -> QueueOffer:
        return self.transition(
            item_id,
            "selected_shadow",
            reason,
            run_id,
        )

    def requeue_expired_explicitly(
        self,
        item_id: int,
        expires_at: datetime,
        reason="Reabertura explícita de oferta expirada.",
    ) -> QueueOffer:
        return self.repository.transition(
            item_id,
            ("expired",),
            "queued",
            reason,
            fields={
                "expires_at": expires_at,
                "available_at": self.now(),
            },
        )

    def list(self, statuses=None, limit=500):
        return self.repository.list_by_status(statuses, limit)

    def expire_due(self, now=None):
        return self.repository.expire_due(now or self.now())

    def release_expired_reservations(self, now=None):
        return self.repository.release_expired_reservations(
            now or self.now()
        )

    @staticmethod
    def priority(ranked: RankedOffer) -> float:
        return (
            ranked.score.total * 100
            + ranked.score.confidence
        )

    @staticmethod
    def now():
        return datetime.now(timezone.utc)
