import re


class Parser:

    MOJIBAKE_MARKERS = (
        "Ã",
        "Â",
        "â€",
        "â€“",
        "â€”",
        "â„¢",
    )

    @staticmethod
    def fix_encoding(text):

        if not text:
            return ""

        fixed = text

        for _ in range(2):

            if not any(marker in fixed for marker in Parser.MOJIBAKE_MARKERS):
                break

            try:
                candidate = fixed.encode("cp1252").decode("utf-8")
            except UnicodeError:
                break

            if candidate == fixed:
                break

            fixed = candidate

        return fixed

    # ==========================================

    @staticmethod
    def clean_text(text):

        if not text:
            return ""

        text = Parser.fix_encoding(str(text))

        text = text.replace("\n", " ")
        text = text.replace("\t", " ")

        while "  " in text:
            text = text.replace("  ", " ")

        return text.strip()

    # ==========================================

    @staticmethod
    def clean_price(price):

        value = Parser.price_to_float(price)
        if value <= 0:
            return ""
        return Parser.format_brl(value)

    # ==========================================

    @staticmethod
    def price_to_float(price):

        if price is None or price == "":
            return 0.0
        if isinstance(price, (int, float)):
            return float(price)
        text = Parser.clean_text(str(price))
        text = re.sub(r"[^\d,.\-]", "", text)
        if not text:
            return 0.0
        negative = text.startswith("-")
        text = text.lstrip("-")
        if "," in text and "." in text:
            decimal = "," if text.rfind(",") > text.rfind(".") else "."
            thousands = "." if decimal == "," else ","
            text = text.replace(thousands, "")
            text = text.replace(decimal, ".")
        elif "," in text:
            parts = text.split(",")
            if len(parts[-1]) in (1, 2):
                text = "".join(parts[:-1]) + "." + parts[-1]
            else:
                text = "".join(parts)
        elif "." in text:
            parts = text.split(".")
            if len(parts) == 2 and len(parts[-1]) in (1, 2):
                text = parts[0] + "." + parts[-1]
            elif len(parts[-1]) in (1, 2):
                text = "".join(parts[:-1]) + "." + parts[-1]
            else:
                text = "".join(parts)
        if negative:
            text = "-" + text
        try:
            return float(text)
        except (TypeError, ValueError):
            return 0.0

    # ==========================================

    @staticmethod
    def format_brl(value, include_symbol=False):

        number = Parser.price_to_float(value)
        formatted = f"{number:,.2f}"
        formatted = (
            formatted.replace(",", "\0")
            .replace(".", ",")
            .replace("\0", ".")
        )
        return f"R$ {formatted}" if include_symbol else formatted

    # ==========================================

    @staticmethod
    def absolute_link(link, base):

        if not link:
            return ""

        if link.startswith("http"):
            return link

        if link.startswith("/"):

            return base.rstrip("/") + link

        return base.rstrip("/") + "/" + link

    # ==========================================

    @staticmethod
    def remove_tracking(url):

        if not url:
            return ""

        return re.split(r"\?|#", url)[0]
