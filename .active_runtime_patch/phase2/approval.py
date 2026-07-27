from typing import Dict, Iterable

from .models import ApprovalBatch, ApprovalDecision


class ApprovalWorkspace:
    """Mantém decisões em lote sem alterar a interface ou enviar produtos."""

    def create(self, batch_id: str, product_keys: Iterable[str]) -> ApprovalBatch:
        keys = tuple(dict.fromkeys(product_keys))
        return ApprovalBatch(
            batch_id=batch_id,
            product_keys=keys,
            decisions={key: ApprovalDecision.PENDING for key in keys},
        )

    def decide(
        self,
        batch: ApprovalBatch,
        product_key: str,
        decision: ApprovalDecision,
    ) -> ApprovalBatch:
        if product_key not in batch.product_keys:
            raise KeyError(product_key)
        decisions: Dict[str, ApprovalDecision] = dict(batch.decisions)
        decisions[product_key] = decision
        return ApprovalBatch(batch.batch_id, batch.product_keys, decisions)
