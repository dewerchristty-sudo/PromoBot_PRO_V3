import logging
import math
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from enum import Enum
from typing import Any, Mapping, Optional

from .models import MessageStyle, NotificationOffer, PreparedNotification


logger = logging.getLogger(__name__)
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _decimal_value(value: Any) -> Optional[Decimal]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    if isinstance(value, (int, float)):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            return None

    text = str(value).strip().replace("R$", "").replace("%", "").strip()
    if not text:
        return None
    text = text.replace(" ", "")
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        decimal = Decimal(text)
    except InvalidOperation:
        return None
    return decimal if decimal.is_finite() else None


def format_brl_currency(value: Any) -> str:
    decimal = _decimal_value(value)
    if decimal is None or decimal < 0:
        return ""
    rounded = decimal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    integer, fraction = f"{rounded:.2f}".split(".")
    groups = []
    while integer:
        groups.append(integer[-3:])
        integer = integer[:-3]
    return f"R$ {'.'.join(reversed(groups))},{fraction}"


def format_discount_percent(value: Any) -> str:
    decimal = _decimal_value(value)
    if decimal is None or decimal < 0:
        return ""
    rounded = decimal.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    number = (
        str(int(rounded))
        if rounded == rounded.to_integral()
        else format(rounded, "f").replace(".", ",")
    )
    return f"{number}% de desconto"


class OfferNotificationFormatter:
    """Gera mensagens; não conhece nem executa canais de publicação."""

    def __init__(
        self,
        opening_text: str = "",
        closing_text: str = "",
    ) -> None:
        self.opening_text = self._safe_text(opening_text)
        self.closing_text = self._safe_text(closing_text)

    def create(
        self,
        offer: NotificationOffer | Mapping[str, Any],
        style: MessageStyle | str = MessageStyle.COMPLETE,
        opening_text: Optional[str] = None,
        closing_text: Optional[str] = None,
    ) -> PreparedNotification:
        normalized = self._normalize_offer(offer)
        selected_style = self._style(style)
        opening = (
            self.opening_text
            if opening_text is None
            else self._safe_text(opening_text)
        )
        closing = (
            self.closing_text
            if closing_text is None
            else self._safe_text(closing_text)
        )

        try:
            lines = self._message_lines(normalized, selected_style)
            message = "\n".join(
                part for part in (opening, "\n".join(lines), closing) if part
            )
        except Exception:
            logger.exception("Falha inesperada ao formatar notificação")
            lines = self._message_lines(NotificationOffer(), selected_style)
            message = "\n".join(part for part in (opening, *lines, closing) if part)

        return PreparedNotification(
            message=message,
            style=selected_style,
            product_link=self._safe_url(normalized.product_link),
            image_link=self._safe_url(normalized.image_link),
        )

    def short(
        self,
        offer: NotificationOffer | Mapping[str, Any],
        **texts: Optional[str],
    ) -> PreparedNotification:
        return self.create(offer, MessageStyle.SHORT, **texts)

    def complete(
        self,
        offer: NotificationOffer | Mapping[str, Any],
        **texts: Optional[str],
    ) -> PreparedNotification:
        return self.create(offer, MessageStyle.COMPLETE, **texts)

    def _message_lines(
        self,
        offer: NotificationOffer,
        style: MessageStyle,
    ) -> list[str]:
        title = self._safe_text(offer.title)
        store = self._safe_text(offer.store)
        classification = self._classification(offer.classification)
        current = self._money(offer.current_price, "current_price")
        previous = self._money(offer.previous_price, "previous_price")
        savings_value = offer.savings
        discount_value = offer.discount_percent
        current_number = _decimal_value(offer.current_price)
        previous_number = _decimal_value(offer.previous_price)
        if (
            savings_value in (None, "")
            and current_number is not None
            and previous_number is not None
            and previous_number > current_number
        ):
            savings_value = previous_number - current_number
        if (
            discount_value in (None, "")
            and current_number is not None
            and previous_number is not None
            and previous_number > current_number
            and previous_number > 0
        ):
            discount_value = (
                (previous_number - current_number) / previous_number
            ) * Decimal("100")
        savings = self._money(savings_value, "savings")
        discount = self._percent(discount_value)
        product_link = self._safe_url(offer.product_link)
        image_link = self._safe_url(offer.image_link)

        lines = []
        if title:
            lines.append(title)
        if current:
            lines.append(f"Preço: {current}")
        if discount:
            lines.append(discount)
        if classification:
            lines.append(f"Classificação: {classification}")
        if product_link:
            lines.append(product_link)

        if style is MessageStyle.COMPLETE:
            detail_lines = []
            if store:
                detail_lines.append(f"Loja: {store}")
            if previous:
                detail_lines.append(f"Preço anterior: {previous}")
            if savings:
                detail_lines.append(f"Economia: {savings}")
            if image_link:
                detail_lines.append(f"Imagem: {image_link}")
            insertion_point = 1 if title else 0
            lines[insertion_point:insertion_point] = detail_lines

        return lines

    @staticmethod
    def _normalize_offer(
        offer: NotificationOffer | Mapping[str, Any],
    ) -> NotificationOffer:
        if isinstance(offer, NotificationOffer):
            return offer
        if isinstance(offer, Mapping):
            try:
                return NotificationOffer.from_mapping(offer)
            except Exception:
                logger.exception("Dados inválidos ao criar NotificationOffer")
                return NotificationOffer()
        logger.error(
            "Oferta inválida para notificação: %s",
            type(offer).__name__,
        )
        return NotificationOffer()

    @staticmethod
    def _style(style: MessageStyle | str) -> MessageStyle:
        try:
            return MessageStyle(style)
        except (TypeError, ValueError):
            logger.warning("Modelo de mensagem inválido: %r", style)
            return MessageStyle.COMPLETE

    @staticmethod
    def _safe_text(value: Any) -> str:
        if value is None:
            return ""
        try:
            text = str(value)
        except Exception:
            logger.exception("Campo textual inválido")
            return ""
        text = _CONTROL_CHARACTERS.sub("", text)
        return " ".join(text.split())

    @classmethod
    def _safe_url(cls, value: Any) -> str:
        text = cls._safe_text(value)
        return text if text.startswith(("http://", "https://")) else ""

    @classmethod
    def _classification(cls, value: Any) -> str:
        if isinstance(value, Enum):
            value = value.value
        return cls._safe_text(value)

    @staticmethod
    def _money(value: Any, field: str) -> str:
        result = format_brl_currency(value)
        if value not in (None, "") and not result:
            logger.warning("Valor monetário inválido em %s: %r", field, value)
        return result

    @staticmethod
    def _percent(value: Any) -> str:
        result = format_discount_percent(value)
        if value not in (None, "") and not result:
            logger.warning("Percentual de desconto inválido: %r", value)
        return result
