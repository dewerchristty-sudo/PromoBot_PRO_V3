from src.scraper import Locator
from src.scraper import Parser
from src.scraper import Waits


class StoreScraper:

    def __init__(self, browser_manager):

        self.browser_manager = browser_manager

    # ==========================================

    @property
    def base_url(self):
        return ""

    @property
    def name(self):
        return ""

    # ==========================================

    def open(self, product):

        page = self.browser_manager.new_page()

        url = self.base_url.format(
            product.replace(" ", "-")
        )

        print(f"\n>>> {self.name}")
        print(f"Abrindo: {url}")

        page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=60000
        )

        Waits.full(page)

        return page

    # ==========================================

    def close(self, page):

        page.close()

    # ==========================================

    def text(self, element):

        return Parser.clean_text(
            Locator.text(element)
        )

    # ==========================================

    def price(self, text):

        return Parser.clean_price(text)

    # ==========================================

    def link(self, url, base):

        return Parser.remove_tracking(
            Parser.absolute_link(url, base)
        )