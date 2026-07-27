from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re


CENT = Decimal("0.01")


def money(value):
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, (int, float)):
        result = Decimal(str(value))
    else:
        text = re.sub(r"[^\d,.-]", "", str(value or "").strip())
        if not text:
            return None
        if "," in text:
            text = text.replace(".", "").replace(",", ".")
        elif text.count(".") > 1:
            text = text.replace(".", "")
        elif re.fullmatch(r"\d{1,3}\.\d{3}", text):
            text = text.replace(".", "")
        try:
            result = Decimal(text)
        except InvalidOperation:
            return None
    if not result.is_finite():
        return None
    return result.quantize(CENT, rounding=ROUND_HALF_UP)


def percent_change(current, reference):
    if current is None or reference is None or reference <= 0:
        return None
    return (
        (current - reference) / reference * Decimal("100")
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
