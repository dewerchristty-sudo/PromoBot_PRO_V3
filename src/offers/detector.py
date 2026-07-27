"""Módulo independente de detecção inteligente de ofertas.

Totalmente desacoplado de lojas, banco de dados e monitoramento.
Preparado para integração futura com notificações automáticas.
"""

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Optional
import logging


class OfferRating(str, Enum):
    """Classificação da oferta com base no desconto identificado."""

    NONE = "none"
    COMMON = "common"
    GOOD = "good"
    EXCELLENT = "excellent"

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class OfferDetection:
    """Resultado completo da análise de uma oferta."""

    current_price: float
    previous_price: Optional[float]
    savings: Optional[float]
    discount_percent: Optional[float]
    rating: OfferRating
    has_previous_price: bool
    is_price_drop: bool
    analyzed_at: datetime
    thresholds_used: Mapping[str, float]

    def to_dict(self) -> dict[str, Any]:
        """Serializa o resultado para dict (útil para logs e futuras notificações)."""
        return {
            "current_price": self.current_price,
            "previous_price": self.previous_price,
            "savings": self.savings,
            "discount_percent": self.discount_percent,
            "rating": str(self.rating),
            "has_previous_price": self.has_previous_price,
            "is_price_drop": self.is_price_drop,
            "analyzed_at": self.analyzed_at.isoformat(),
            "thresholds_used": dict(self.thresholds_used),
        }


@dataclass(frozen=True, slots=True)
class OfferDetectorConfig:
    """Configuração dos limites de desconto para classificação de ofertas.

    Todos os valores percentuais devem estar em pontos percentuais (ex: 5.0 = 5%).
    """

    good_discount_percent: float = 10.0
    excellent_discount_percent: float = 25.0

    def __post_init__(self) -> None:
        """Valida a consistência dos limites na criação."""
        if self.good_discount_percent < 0:
            raise ValueError(
                f"good_discount_percent deve ser >= 0, "
                f"obtido {self.good_discount_percent}"
            )
        if self.excellent_discount_percent < 0:
            raise ValueError(
                f"excellent_discount_percent deve ser >= 0, "
                f"obtido {self.excellent_discount_percent}"
            )
        if self.good_discount_percent > self.excellent_discount_percent:
            raise ValueError(
                f"good_discount_percent ({self.good_discount_percent}) "
                f"não pode ser maior que "
                f"excellent_discount_percent ({self.excellent_discount_percent})"
            )

    def validate(self) -> None:
        """Valida a consistência dos limites configurados (método público)."""
        self.__post_init__()

    def to_dict(self) -> dict[str, float]:
        """Retorna os limites como dicionário."""
        return {
            "good_discount_percent": self.good_discount_percent,
            "excellent_discount_percent": self.excellent_discount_percent,
        }


class OfferDetector:
    """Detector inteligente de ofertas independente de lojas e persistência.

    Responsabilidades:
    - Detectar queda de preço
    - Calcular economia em reais
    - Calcular percentual de desconto
    - Comparar preço atual com histórico
    - Classificar ofertas (comum, boa, excelente)
    - Gerar objeto estruturado com metadados da análise
    - Registrar logs
    """

    def __init__(
        self,
        config: Optional[OfferDetectorConfig] = None,
        logger: Optional[logging.Logger] = None,
    ):
        raw = config or OfferDetectorConfig()
        raw.validate()
        self.config = raw
        self.logger = logger or logging.getLogger("promobot.offer_detector")

    def analyze(
        self,
        current_price: float,
        previous_price: Optional[float] = None,
        analyzed_at: Optional[datetime] = None,
    ) -> OfferDetection:
        """Analisa uma oferta e retorna a detecção completa.

        Args:
            current_price: Preço atual do produto (obrigatório).
            previous_price: Preço anterior para comparação (opcional).
            analyzed_at: Momento da análise (opcional, usa UTC now).

        Returns:
            OfferDetection com todos os campos preenchidos.

        Raises:
            ValueError: Se current_price for inválido (negativo ou zero).
        """
        self._validate_price_type(current_price, "current_price")
        if previous_price is not None:
            self._validate_price_type(previous_price, "previous_price")
        if current_price < 0:
            raise ValueError(
                f"current_price não pode ser negativo, obtido {current_price}"
            )

        analyzed_at = analyzed_at or datetime.now(timezone.utc)

        if previous_price is None:
            return self._no_previous_price_result(current_price, analyzed_at)

        if previous_price <= 0:
            self.logger.warning(
                "previous_price inválido (%s); tratando como ausente",
                previous_price,
            )
            return self._no_previous_price_result(current_price, analyzed_at)

        savings = self._calculate_savings(current_price, previous_price)
        discount_percent = self._calculate_discount_percent(
            current_price, previous_price
        )
        is_price_drop = self._detect_price_drop(current_price, previous_price)
        rating = self._classify(discount_percent, is_price_drop)
        thresholds_used = self.config.to_dict()

        self._log_detection(
            current_price=current_price,
            previous_price=previous_price,
            savings=savings,
            discount_percent=discount_percent,
            rating=rating,
            is_price_drop=is_price_drop,
        )

        return OfferDetection(
            current_price=current_price,
            previous_price=previous_price,
            savings=savings,
            discount_percent=discount_percent,
            rating=rating,
            has_previous_price=True,
            is_price_drop=is_price_drop,
            analyzed_at=analyzed_at,
            thresholds_used=thresholds_used,
        )

    def analyze_from_mapping(
        self,
        data: Mapping[str, Any],
        analyzed_at: Optional[datetime] = None,
    ) -> OfferDetection:
        """Analisa uma oferta a partir de um dicionário/mapping.

        Extrai automaticamente 'current_price' (ou 'preco_valor', 'preco')
        e 'previous_price' (ou 'preco_antigo') do mapping.

        Args:
            data: Mapping com os dados do produto.
            analyzed_at: Momento da análise (opcional).

        Returns:
            OfferDetection com todos os campos preenchidos.
        """
        current_price = self._extract_price(
            data,
            "current_price",
            "preco_valor",
            "preco",
        )
        previous_price = self._extract_price(
            data,
            "previous_price",
            "preco_antigo",
        )
        return self.analyze(
            current_price=current_price,
            previous_price=previous_price,
            analyzed_at=analyzed_at or data.get("analyzed_at"),
        )

    def _no_previous_price_result(
        self,
        current_price: float,
        analyzed_at: datetime,
    ) -> OfferDetection:
        """Retorna resultado quando não há preço anterior disponível."""
        self.logger.info(
            "Sem preço anterior para comparação; "
            "preço atual=%.2f",
            current_price,
        )
        return OfferDetection(
            current_price=current_price,
            previous_price=None,
            savings=None,
            discount_percent=None,
            rating=OfferRating.NONE,
            has_previous_price=False,
            is_price_drop=False,
            analyzed_at=analyzed_at,
            thresholds_used=self.config.to_dict(),
        )

    def _calculate_savings(
        self,
        current_price: float,
        previous_price: float,
    ) -> float:
        """Calcula a economia em reais (preço anterior - preço atual)."""
        savings = previous_price - current_price
        return round(max(savings, 0.0), 2)

    def _calculate_discount_percent(
        self,
        current_price: float,
        previous_price: float,
    ) -> Optional[float]:
        """Calcula o percentual de desconto.

        Retorna None se previous_price for zero ou negativo para evitar
        divisão por zero ou percentuais sem sentido.
        """
        if previous_price <= 0:
            return None
        change = ((previous_price - current_price) / previous_price) * 100.0
        return round(max(change, 0.0), 2)

    def _detect_price_drop(
        self,
        current_price: float,
        previous_price: float,
    ) -> bool:
        """Detecta se houve queda de preço (desconsiderando variações mínimas)."""
        if previous_price <= 0:
            return False
        return current_price < previous_price

    def _classify(
        self,
        discount_percent: Optional[float],
        is_price_drop: bool,
    ) -> OfferRating:
        """Classifica a oferta com base no percentual de desconto.

        Regras:
        - Sem desconto ou sem preço anterior → NONE
        - discount_percent >= excellent_discount_percent → EXCELLENT
        - discount_percent >= good_discount_percent → GOOD
        - discount_percent > 0 (mas abaixo de good) → COMMON
        - Sem queda de preço → NONE
        """
        if not is_price_drop or discount_percent is None or discount_percent <= 0:
            return OfferRating.NONE

        if discount_percent >= self.config.excellent_discount_percent:
            return OfferRating.EXCELLENT
        if discount_percent >= self.config.good_discount_percent:
            return OfferRating.GOOD
        return OfferRating.COMMON

    def _validate_price_type(self, price: float, name: str) -> None:
        """Valida se o preço é um tipo numérico válido."""
        if not isinstance(price, (int, float)):
            raise ValueError(
                f"{name} deve ser um número, obtido {type(price).__name__}"
            )

    def _extract_price(
        self,
        data: Mapping[str, Any],
        *keys: str,
    ) -> Optional[float]:
        """Extrai o primeiro valor numérico válido de uma lista de chaves."""
        for key in keys:
            value = data.get(key)
            if value is not None:
                try:
                    return float(value)
                except (ValueError, TypeError):
                    self.logger.debug(
                        "Chave %s com valor não numérico: %r", key, value
                    )
                    continue
        return None

    def _log_detection(
        self,
        current_price: float,
        previous_price: float,
        savings: float,
        discount_percent: float,
        rating: OfferRating,
        is_price_drop: bool,
    ) -> None:
        """Registra log estruturado da detecção."""
        if rating == OfferRating.EXCELLENT:
            level = logging.INFO
        elif rating == OfferRating.GOOD:
            level = logging.INFO
        elif is_price_drop:
            level = logging.DEBUG
        else:
            level = logging.DEBUG

        self.logger.log(
            level,
            "Oferta detectada | preço_atual=%.2f preço_anterior=%.2f "
            "economia=%.2f desconto=%.2f%% classificação=%s queda_preço=%s",
            current_price,
            previous_price,
            savings,
            discount_percent,
            rating,
            is_price_drop,
        )