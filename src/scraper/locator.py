try:
    from playwright.sync_api import TimeoutError
except ModuleNotFoundError:
    TimeoutError = TimeoutError


class Locator:

    @staticmethod
    def count(page, selector):

        try:

            return page.locator(selector).count()

        except Exception:

            return 0

    # ==========================================

    @staticmethod
    def first(page, selector):

        try:

            locator = page.locator(selector)

            if locator.count():

                return locator.first

        except Exception:

            pass

        return None

    # ==========================================

    @staticmethod
    def all(page, selector):

        try:

            return page.locator(selector)

        except Exception:

            return None

    # ==========================================

    @staticmethod
    def text(element):

        try:

            texto = element.text_content()

            if texto:

                return texto.strip()

        except Exception:

            pass

        return ""

    # ==========================================

    @staticmethod
    def attribute(element, attribute):

        try:

            valor = element.get_attribute(attribute)

            if valor:

                return valor.strip()

        except Exception:

            pass

        return ""

    # ==========================================

    @staticmethod
    def wait(page, selector, timeout=10000):

        try:

            page.wait_for_selector(
                selector,
                timeout=timeout
            )

            return True

        except TimeoutError:

            return False
