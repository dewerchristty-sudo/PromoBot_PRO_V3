from dataclasses import dataclass
from typing import Iterable, Optional

from .models import OfferCandidate
from .score import OfferScore


@dataclass(frozen=True, slots=True)
class OfferFilterPolicy:
    minimum_price: Optional[float] = None
    maximum_price: Optional[float] = None
    minimum_discount: Optional[float] = None
    allowed_stores: tuple[str, ...] = ()
    allowed_categories: tuple[str, ...] = ()
    suspicious_discount_percent: float = 90.0


@dataclass(frozen=True, slots=True)
class FilterResult:
    approved: bool
    reasons: tuple[str, ...]
    operational_blocks: tuple[str, ...]
    warnings: tuple[str, ...]
    shadow_mode: bool = True
    blocks_current_flow: bool = False


class OfferFilter:
    """Diagnostica qualidade e operação sem bloquear o fluxo atual."""

    def __init__(self, policy: OfferFilterPolicy | None = None):
        self.policy = policy or OfferFilterPolicy()

    def analyze(self, candidate: OfferCandidate) -> FilterResult:
        reasons: list[str] = []
        blocks: list[str] = []
        warnings: list[str] = []
        current = OfferScore.number(candidate.current_price)
        previous = OfferScore.number(candidate.previous_price)
        historical = OfferScore.number(candidate.historical_reference_price)

        if current <= 0:
            reasons.append("preco_invalido")
        if (
            self.policy.minimum_price is not None
            and current > 0
            and current < self.policy.minimum_price
        ):
            reasons.append("abaixo_do_preco_minimo")
        if (
            self.policy.maximum_price is not None
            and current > self.policy.maximum_price
        ):
            reasons.append("acima_do_preco_maximo")

        reference = historical if historical > current else previous
        discount = OfferScore.discount_percent(current, reference)
        if (
            self.policy.minimum_discount is not None
            and discount < self.policy.minimum_discount
        ):
            reasons.append("abaixo_do_desconto_minimo")
        if discount > self.policy.suspicious_discount_percent:
            reasons.append("dados_suspeitos")
            warnings.append("desconto_acima_de_90_porcento")
        if previous > 0 and current > 0 and previous <= current:
            warnings.append("preco_anterior_inconsistente")

        if self.policy.allowed_stores and not self.allowed(
            candidate.store,
            self.policy.allowed_stores,
        ):
            reasons.append("loja_nao_permitida")
        if self.policy.allowed_categories and not self.allowed(
            candidate.category,
            self.policy.allowed_categories,
        ):
            reasons.append("categoria_nao_permitida")
        if candidate.duplicate:
            reasons.append("produto_duplicado")

        signals = dict(candidate.future_signals or {})
        if (
            not candidate.product_link.strip()
            and not candidate.affiliate_link.strip()
        ):
            blocks.append("link_original_ausente")
        if not candidate.image_url.strip():
            blocks.append("imagem_ausente")
        if (
            bool(signals.get(
                "affiliate_required",
                candidate.store.strip().casefold()
                in {"mercado livre", "shopee", "amazon"},
            ))
            and not candidate.affiliate_link.strip()
        ):
            blocks.append("link_afiliado_ausente")

        return FilterResult(
            approved=not reasons,
            reasons=tuple(reasons),
            operational_blocks=tuple(blocks),
            warnings=tuple(warnings),
        )

    @staticmethod
    def allowed(value: str, allowed_values: Iterable[str]) -> bool:
        normalized = str(value or "").strip().casefold()
        return normalized in {
            str(item or "").strip().casefold()
            for item in allowed_values
        }
