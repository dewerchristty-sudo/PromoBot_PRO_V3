from playwright.sync_api import sync_playwright


class BrowserManager:

    def __init__(self, headless=False):

        self.headless = headless

        self.playwright = None
        self.browser = None
        self.context = None

    def start(self):

        if self.context is not None:
            return self.context

        try:

            self.playwright = sync_playwright().start()

            self.browser = self.playwright.chromium.launch(

                headless=self.headless,

                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--start-maximized",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                ]

            )

            self.context = self.browser.new_context(

                viewport={
                    "width": 1366,
                    "height": 768
                },

                locale="pt-BR",

                timezone_id="America/Sao_Paulo",

                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/138.0.0.0 Safari/537.36"
                ),

                java_script_enabled=True,

                ignore_https_errors=True,

            )

            self.context.set_extra_http_headers({

                "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",

                "Upgrade-Insecure-Requests": "1",

                "DNT": "1",

            })

        except Exception:

            self.close()
            raise

        return self.context

    def new_page(self):

        context = self.start()

        page = context.new_page()

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

    def close(self):

        if self.context:
            self.context.close()
            self.context = None

        if self.browser:
            self.browser.close()
            self.browser = None

        if self.playwright:
            self.playwright.stop()
            self.playwright = None
