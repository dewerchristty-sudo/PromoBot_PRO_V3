import re


class Parser:

    @staticmethod
    def clean_text(text):

        if not text:
            return ""

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