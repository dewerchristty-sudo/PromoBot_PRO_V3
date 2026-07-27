from dataclasses import replace
from datetime import datetime
from typing import Dict, List, Optional

from .models import PublicationPlan


class PublicationQueue:
    """Fila de planejamento em memória; não possui capacidade de envio."""

    def __init__(self) -> None:
        self._plans: Dict[str, PublicationPlan] = {}

    def add(self, plan: PublicationPlan) -> None:
        if plan.plan_id in self._plans:
            raise ValueError(f"Plano já cadastrado: {plan.plan_id}")
        self._plans[plan.plan_id] = plan

    def get(self, plan_id: str) -> Optional[PublicationPlan]:
        return self._plans.get(plan_id)

    def pause(self, plan_id: str) -> PublicationPlan:
        return self._change_pause(plan_id, True)

    def resume(self, plan_id: str) -> PublicationPlan:
        return self._change_pause(plan_id, False)

    def due(self, now: Optional[datetime] = None) -> List[PublicationPlan]:
        reference = now or datetime.now()
        return sorted(
            (
                plan
                for plan in self._plans.values()
                if not plan.paused and plan.scheduled_for <= reference
            ),
            key=lambda plan: (plan.scheduled_for, plan.plan_id),
        )

    def pending(self) -> List[PublicationPlan]:
        return sorted(
            self._plans.values(),
            key=lambda plan: (plan.scheduled_for, plan.plan_id),
        )

    def _change_pause(self, plan_id: str, paused: bool) -> PublicationPlan:
        plan = self._plans.get(plan_id)
        if plan is None:
            raise KeyError(plan_id)
        changed = replace(plan, paused=paused)
        self._plans[plan_id] = changed
        return changed
