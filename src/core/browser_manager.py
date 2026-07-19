from typing import Any, Optional
from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page

from src.constants import (
    BROWSER_VIEWPORT_WIDTH,
    BROWSER_VIEWPORT_HEIGHT,
    BROWSER_TIMEZONE,
    BROWSER_LOCALE,
    BROWSER_USER_AGENT,
)


class BrowserManager:

    def __init__(self, headless: bool = True) -> None:

        self.headless = headless

        self.playwright: Optional[Any] = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None

    def start(self) -> BrowserContext:

        if self.context is not None:
            return self.context

        try:

            self.playwright = sync_playwright().start()

            args = [
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ]

            if self.headless:
                args.append("--headless=new")
            else:
                args.append("--start-maximized")

            self.browser = self.playwright.chromium.launch(

                headless=self.headless,

                args=args
            )

            self.context = self.browser.new_context(

                viewport={
                    "width": BROWSER_VIEWPORT_WIDTH,
                    "height": BROWSER_VIEWPORT_HEIGHT
                },

                locale=BROWSER_LOCALE,

                timezone_id=BROWSER_TIMEZONE,

                user_agent=BROWSER_USER_AGENT,

                java_script_enabled=True,

                ignore_https_errors=True,

            )

        except Exception:

            self.close()
            raise

        return self.context

    def new_page(self, stealth: bool = True) -> Page:

        context = self.start()

        page = context.new_page()

        if stealth:
            page.add_init_script("""

Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined
});

Object.defineProperty(navigator, 'platform', {
    get: () => 'Win32'
});

Object.defineProperty(navigator, 'language', {
    get: () => 'pt-BR'
});

Object.defineProperty(navigator, 'languages', {
    get: () => ['pt-BR', 'pt', 'en-US']
});

""")

        return page

    def close(self) -> None:

        if self.context:
            self.context.close()
            self.context = None

        if self.browser:
            self.browser.close()
            self.browser = None

        if self.playwright:
            self.playwright.stop()
            self.playwright = None
