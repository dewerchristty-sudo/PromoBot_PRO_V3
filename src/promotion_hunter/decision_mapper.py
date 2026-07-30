from __future__ import annotations

from typing import Any

from .models import DecisionStatus, HunterDecision, NormalizedProduct


class DecisionMapper:
    PENDING_REASON_PRIORITY = (
        "preco_sem_historico",
        "imagem_ausente",
        "link_afiliado_ausente",
        "categoria_invalida",
        "categoria_nao_permitida",
        "dados_incompletos",
    )
    PENDING_REASONS = frozenset(PENDING_REASON_PRIORITY)

    @staticmethod
    def _get(value: Any, name: str, default: Any = None) -> Any:
        if isinstance(value, dict):
            return value.get(name, default)
        return getattr(value, name, default)

    def map(
        self,
        product: NormalizedProduct,
        pipeline_item: Any,
    ) -> HunterDecision:
        diagnostic = self._get(pipeline_item, "diagnostic", {}) or {}
        analysis = self._get(pipeline_item, "analysis")
        score_result = self._get(analysis, "score")
        score = self._get(diagnostic, "score", self._get(score_result, "total"))
        classification = self._get(
            diagnostic,
            "classification",
            self._get(score_result, "classification"),
        )
        run_id = self._get(pipeline_item, "run_id")
        error = str(self._get(pipeline_item, "error", "") or "")
        reason = str(self._get(diagnostic, "reason", "") or error)
        approved = bool(self._get(diagnostic, "filter_approved", False))
        duplicate = bool(self._get(diagnostic, "duplicate", False))
        operational_blocks = tuple(
            self._get(diagnostic, "operational_blocks", ()) or ()
        )
        queue_status = str(self._get(diagnostic, "queue_status", "") or "")
        candidate = self._get(analysis, "candidate")
        delivery_payload = {
            "title": self._get(candidate, "title", product.title),
            "store": self._get(candidate, "store", product.store),
            "current_price": self._get(
                candidate, "current_price", product.current_price
            ),
            "previous_price": self._get(
                candidate, "previous_price", product.previous_price
            ),
            "image_url": self._get(
                candidate, "image_url", product.image_url
            ),
            "product_url": (
                self._get(candidate, "affiliate_link", "")
                or self._get(candidate, "product_link", "")
                or product.url
            ),
        }

        reasons = tuple(filter(None, (
            reason,
            *map(str, operational_blocks),
        )))
        tokens = {
            token.strip()
            for combined in reasons
            for token in combined.replace(";", ",").split(",")
            if token.strip()
        }

        if error:
            status = DecisionStatus.PENDING
            reason = " ".join(error.split())[:300] or "erro_pipeline"
        elif duplicate:
            status = DecisionStatus.DISCARDED
            reason = "duplicidade_ativa"
        elif tokens & self.PENDING_REASONS:
            status = DecisionStatus.PENDING
            reason = next(
                item for item in self.PENDING_REASON_PRIORITY
                if item in tokens
            )
        elif operational_blocks:
            status = DecisionStatus.DISCARDED
            reason = str(operational_blocks[0])
        elif approved and not operational_blocks and queue_status != "discarded":
            status = DecisionStatus.APPROVED
            reason = "oferta_aprovada"
        else:
            status = DecisionStatus.DISCARDED
            reason = (
                reason
                if reason and reason != "oferta_aprovada"
                else "filtro_reprovado"
            )

        delivery_payload["pipeline_reason"] = str(
            self._get(diagnostic, "reason", "") or ""
        )
        delivery_payload["operational_blocks"] = operational_blocks

        return HunterDecision(
            product_key=product.deduplication_key,
            status=status,
            reason=reason,
            score=float(score) if score is not None else None,
            classification=(
                str(classification) if classification is not None else None
            ),
            pipeline_run_id=str(run_id) if run_id else None,
            source_ids=product.source_ids,
            delivery_payload=delivery_payload,
        )
