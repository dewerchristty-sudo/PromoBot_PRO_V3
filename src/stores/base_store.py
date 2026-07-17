from abc import ABC, abstractmethod

from src.core.browser_manager import BrowserManager
from src.scraper import StoreScraper


class BaseStore(StoreScraper, ABC):

    def __init__(self, browser_manager=None):

        if browser_manager is None:

            browser_manager = BrowserManager(
                headless=True
            )

        super().__init__(browser_manager)

    # ==========================================

    @property
    @abstractmethod
    def name(self):
        pass

    @property
    @abstractmethod
    def base_url(self):
        pass

    # ==========================================

    @abstractmethod
    def search(self, product):
        pass
