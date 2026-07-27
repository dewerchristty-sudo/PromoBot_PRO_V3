import math
import unicodedata
from typing import Any

from .models import OfferCandidate, ScoreResult
from .policy import OfferScorePolicy


class OfferScore:
    """Score analitico independente de fila, afiliacao e transporte."""

    def __init__(self, policy: OfferScorePolicy | None = None):
        self.policy = policy or OfferScorePolicy()

    def calculate(self, candidate: OfferCandidate) -> ScoreResult:
        components: dict[str, float] = {}
        reasons: list[str] = []
        current = self.number(candidate.current_price)
        reference, reference_source = self.discount_reference(candidate, current)
        discount = self.discount_percent(current, reference)
        signals = dict(candidate.future_signals or {})
        history_reliable = bool(signals.get(
            "history_reliable_for_score",
            candidate.price_sample_count >= self.policy.minimum_reliable_samples,
        ))
        verified_discount = bool(
            reference > current > 0
            and (
                candidate.previous_price_validated
                or reference_source == "historico real"
                or signals.get("discount_verified")
            )
        )

        components["base"] = 0.0
        components["valid_price"] = (
            self.policy.valid_price_points if current > 0 else 0.0
        )
        components["image"] = (
            self.policy.image_points if candidate.image_url.strip() else 0.0
        )
        components["original_link"] = (
            self.policy.original_link_points
            if candidate.product_link.strip() else 0.0
        )
        # Afiliacao e somente prontidao operacional.
        components["affiliate_link"] = 0.0
        components["discount"] = self.policy.points_for_discount(discount)
        components["price_history"] = self.history_points(
            candidate, current, history_reliable
        )
        components["history_signal"] = (
            self.policy.falling_trend_points
            if history_reliable and signals.get("history_trend") == "caiu"
            else 0.0
        )
        if history_reliable and signals.get("history_is_new_record"):
            components["history_signal"] += self.policy.new_record_points
        components["history_signal"] = min(
            components["history_signal"], 5.0
        )
        components["seller_reputation"] = self.lookup_points(
            self.policy.seller_reputation_points,
            candidate.seller_reputation,
        )
        components["trusted_store"] = (
            self.policy.official_store_points
            if candidate.official_store
            else (
                self.policy.trusted_store_points
                if candidate.trusted_store else 0.0
            )
        )
        components["category_demand"] = self.lookup_points(
            self.policy.category_demand_points,
            candidate.category_demand,
        )
        if candidate.category.strip() and components["category_demand"] == 0:
            components["category_demand"] = self.policy.category_known_points
        title_quality = str(signals.get("title_quality", "")).upper()
        components["title_quality"] = (
            self.policy.title_good_points
            if title_quality == "GOOD"
            else (
                self.policy.title_acceptable_points
                if title_quality == "ACCEPTABLE" else 0.0
            )
        )
        components["popularity"] = self.popularity_points(candidate)
        components["availability"] = (
            self.policy.availability_points
            if candidate.stock_available is True
            or self.normalize_label(candidate.availability)
            in {"in stock", "em estoque", "available", "disponivel"}
            else 0.0
        )
        components["coupon"] = (
            self.policy.coupon_points if candidate.has_coupon else 0.0
        )
        components["free_shipping"] = (
            self.policy.free_shipping_points if candidate.free_shipping else 0.0
        )
        components["cashback"] = (
            self.policy.cashback_points if candidate.cashback else 0.0
        )
        components["bonus"] = min(
            components["coupon"]
            + components["free_shipping"]
            + components["cashback"],
            5.0,
        )
        penalty = 0.0
        if discount > self.policy.suspicious_discount_percent:
            penalty -= 25.0
            reasons.append(
                f"Desconto suspeito de {discount:.1f}% para revisao."
            )
        if current <= 0:
            penalty -= 50.0
        components["penalties"] = penalty
        # Mantido apenas como campo compativel; nao soma ao Score.
        components["data_confidence"] = 0.0

        confidence = self.promotion_confidence(
            candidate, current, verified_discount, history_reliable
        )
        if reference_source:
            reasons.append(
                f"Desconto calculado usando {reference_source}: {discount:.1f}%."
            )
        else:
            reasons.append("Sem referencia confiavel para calcular desconto.")
        if not history_reliable:
            reasons.append("Historico ainda insuficiente ou concentrado no tempo.")
        if not verified_discount:
            reasons.append("Desconto nao confirmado por evidencia verificavel.")

        scoring_components = (
            "base", "valid_price", "image", "original_link",
            "affiliate_link", "discount", "price_history",
            "history_signal",
            "seller_reputation", "trusted_store", "category_demand",
            "title_quality", "popularity", "availability", "bonus",
            "penalties",
        )
        raw_total = sum(components[name] for name in scoring_components)
        cap = self.policy.maximum_total
        if not verified_discount and not history_reliable:
            cap = self.policy.no_discount_no_history_cap
            reasons.append(
                f"Score limitado a {cap:.0f}: sem desconto e historico confiaveis."
            )
        elif not verified_discount or not history_reliable:
            cap = self.policy.partial_evidence_cap
            reasons.append(
                f"Score limitado a {cap:.0f}: evidencia promocional parcial."
            )
        elif confidence < self.policy.exceptional_confidence_minimum:
            cap = 89.0
            reasons.append(
                "Score excepcional exige confianca promocional de pelo menos "
                f"{self.policy.exceptional_confidence_minimum:.0f}."
            )

        total = min(max(raw_total, self.policy.minimum_total), cap)
        return ScoreResult(
            total=round(total, 2),
            classification=self.policy.classify(total),
            components=components,
            policy_version=self.policy.policy_version,
            confidence=round(confidence, 2),
            reasons=tuple(reasons),
        )

    def discount_reference(
        self,
        candidate: OfferCandidate,
        current: float,
    ) -> tuple[float, str]:
        historical = self.number(candidate.historical_reference_price)
        previous = self.number(candidate.previous_price)
        signals = dict(candidate.future_signals or {})
        history_reliable = bool(signals.get(
            "history_reliable_for_score",
            candidate.price_sample_count >= self.policy.minimum_reliable_samples,
        ))
        if history_reliable and historical > current > 0:
            return historical, "historico real"
        if candidate.previous_price_validated and previous > current > 0:
            return previous, "preco anterior validado"
        if previous > current > 0:
            return previous, "preco anterior anunciado"
        return 0.0, ""

    @staticmethod
    def discount_percent(current: float, reference: float) -> float:
        if current <= 0 or reference <= 0 or reference <= current:
            return 0.0
        value = ((reference - current) / reference) * 100
        return value if math.isfinite(value) else 0.0

    def history_points(
        self,
        candidate: OfferCandidate,
        current: float,
        reliable: bool | None = None,
    ) -> float:
        minimum = self.number(candidate.historical_minimum)
        reliable = (
            candidate.price_sample_count >= self.policy.minimum_reliable_samples
            if reliable is None else reliable
        )
        if current <= 0 or minimum <= 0 or not reliable:
            return 0.0
        if current <= minimum:
            return self.policy.historical_low_points
        distance = ((current - minimum) / minimum) * 100
        if distance <= self.policy.historical_near_low_percent:
            return self.policy.historical_near_low_points
        return 0.0

    def promotion_confidence(
        self,
        candidate: OfferCandidate,
        current: float,
        verified_discount: bool,
        history_reliable: bool,
    ) -> float:
        points = 20.0 if current > 0 else 0.0
        points += 20.0 if verified_discount else 0.0
        points += 25.0 if history_reliable else 0.0
        points += 10.0 if candidate.seller_reputation.strip() else 0.0
        points += (
            10.0
            if candidate.rating or candidate.review_count or candidate.sold_count
            else 0.0
        )
        points += (
            5.0
            if candidate.stock_available is not None or candidate.availability
            else 0.0
        )
        points += 5.0 if candidate.category.strip() else 0.0
        if (
            candidate.title.strip() and candidate.store.strip()
            and candidate.image_url.strip() and candidate.product_link.strip()
        ):
            points += 5.0
        return min(points, 100.0)

    def confidence_points(
        self,
        candidate: OfferCandidate,
        current: float,
        reference: float,
    ) -> float:
        return self.promotion_confidence(
            candidate,
            current,
            bool(reference > current > 0),
            candidate.price_sample_count >= self.policy.minimum_reliable_samples,
        )

    def popularity_points(self, candidate: OfferCandidate) -> float:
        points = 0.0
        rating = self.number(candidate.rating)
        if rating >= 4.5 and candidate.review_count >= 10:
            points += self.policy.rating_points
        elif rating >= 4.0 and candidate.review_count >= 5:
            points += self.policy.rating_points / 2
        if candidate.sold_count >= 1000:
            points += self.policy.sales_points
        elif candidate.sold_count >= 100:
            points += self.policy.sales_points * 0.6
        elif candidate.sold_count >= 10:
            points += self.policy.sales_points * 0.3
        return min(points, self.policy.rating_points + self.policy.sales_points)

    @classmethod
    def lookup_points(cls, mapping: Any, value: str) -> float:
        normalized = cls.normalize_label(value)
        for label, points in mapping.items():
            if cls.normalize_label(label) == normalized:
                return float(points)
        return 0.0

    @staticmethod
    def normalize_label(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", str(value or "").casefold())
        return "".join(
            character for character in normalized
            if not unicodedata.combining(character)
        ).strip()

    @staticmethod
    def number(value: Any) -> float:
        if isinstance(value, bool):
            return 0.0
        if isinstance(value, (int, float)):
            result = float(value)
            return result if math.isfinite(result) else 0.0
        text = str(value or "").strip()
        if not text:
            return 0.0
        text = "".join(
            character for character in text
            if character.isdigit() or character in ",.-"
        )
        if "," in text:
            text = text.replace(".", "").replace(",", ".")
        try:
            result = float(text)
            return result if math.isfinite(result) else 0.0
        except (TypeError, ValueError):
            return 0.0
