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

        if not price:
            return ""

        price = Parser.clean_text(price)

        price = price.replace("R$", "")
        price = price.replace(" ", "")

        return price.strip()

    # ==========================================

    @staticmethod
    def price_to_float(price):

        if not price:
            return 0.0

        price = Parser.clean_price(price)

        price = price.replace(".", "")
        price = price.replace(",", ".")

        try:
            return float(price)

        except Exception:
            return 0.0

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
