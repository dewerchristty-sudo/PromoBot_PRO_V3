import os
from pathlib import Path

from playwright.sync_api import sync_playwright

from src.constants import (
    BROWSER_LOCALE,
    BROWSER_TIMEZONE,
    BROWSER_USER_AGENT,
    BROWSER_VIEWPORT_HEIGHT,
    BROWSER_VIEWPORT_WIDTH,
)


class MercadoLivrePersistentContext:
    """Perfil Playwright isolado; nunca acessa o perfil pessoal do Chrome."""

    def __init__(self, profile_path=None, headless=None, playwright_factory=None):
        configured = profile_path or os.getenv(
            "MERCADO_LIVRE_PROFILE_PATH",
            "data/browser_profiles/mercado_livre",
        )
        self.profile_path = Path(configured)
        self.headless = (
            self.boolean_env("MERCADO_LIVRE_HEADLESS", True)
            if headless is None else bool(headless)
        )
        self.playwright_factory = playwright_factory or sync_playwright
        self.playwright = None
        self.context = None
        self.profile_created = False
        self.profile_reused = False

    @staticmethod
    def enabled():
        return MercadoLivrePersistentContext.boolean_env(
            "MERCADO_LIVRE_PERSISTENT_PROFILE_ENABLED", True
        )

    def start(self):
        if self.context is not None:
            return self.context
        if self.profile_path.exists() and not self.profile_path.is_dir():
            raise ValueError(
                f"Caminho do perfil não é uma pasta: {self.profile_path}"
            )
        self.profile_reused = self.profile_path.exists() and any(
            self.profile_path.iterdir()
        )
        self.profile_path.mkdir(parents=True, exist_ok=True)
        self.profile_created = not self.profile_reused
        self.playwright = self.playwright_factory().start()
        try:
            self.context = self.playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_path.resolve()),
                headless=self.headless,
                viewport={
                    "width": BROWSER_VIEWPORT_WIDTH,
                    "height": BROWSER_VIEWPORT_HEIGHT,
                },
                locale=BROWSER_LOCALE,
                timezone_id=BROWSER_TIMEZONE,
                user_agent=BROWSER_USER_AGENT,
                java_script_enabled=True,
                ignore_https_errors=True,
                args=(
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                ),
            )
        except Exception:
            self.close()
            raise
        return self.context

    def new_page(self, stealth=True):
        context = self.start()
        page = context.new_page()
        if stealth:
            page.add_init_script("""
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'language', {get: () => 'pt-BR'});
Object.defineProperty(navigator, 'languages', {
    get: () => ['pt-BR', 'pt', 'en-US']
});
""")
        return page

    def status(self):
        return {
            "profile_path": str(self.profile_path),
            "profile_created": self.profile_created,
            "profile_reused": self.profile_reused,
            "headless": self.headless,
            "context_open": self.context is not None,
        }

    def close(self):
        if self.context is not None:
            self.context.close()
            self.context = None
        if self.playwright is not None:
            self.playwright.stop()
            self.playwright = None

    @staticmethod
    def boolean_env(name, default):
        value = os.getenv(name)
        if value is None:
            return bool(default)
        return value.strip().casefold() in {"1", "true", "yes", "on", "sim"}
