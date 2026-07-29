from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts import validate_shopee_visible
from src.core.browser_manager import BrowserManager


class BrowserManagerTest(unittest.TestCase):

    @patch("src.core.browser_manager.sync_playwright")
    def test_default_context_remains_temporary(self, playwright_factory):
        playwright = playwright_factory.return_value.start.return_value
        browser = playwright.chromium.launch.return_value
        context = browser.new_context.return_value
        manager = BrowserManager()

        self.assertIs(manager.start(), context)

        playwright.chromium.launch.assert_called_once()
        browser.new_context.assert_called_once()
        playwright.chromium.launch_persistent_context.assert_not_called()
        manager.close()

    @patch("src.core.browser_manager.sync_playwright")
    def test_explicit_profile_uses_persistent_context(self, playwright_factory):
        playwright = playwright_factory.return_value.start.return_value
        context = playwright.chromium.launch_persistent_context.return_value
        with tempfile.TemporaryDirectory() as temporary:
            profile = Path(temporary) / "shopee_playwright"
            manager = BrowserManager(
                headless=False,
                user_data_dir=profile,
            )

            self.assertIs(manager.start(), context)

            call = playwright.chromium.launch_persistent_context.call_args
            self.assertEqual(
                call.kwargs["user_data_dir"],
                str(profile.resolve()),
            )
            self.assertFalse(call.kwargs["headless"])
            playwright.chromium.launch.assert_not_called()
            manager.close()
            manager.close()

        context.close.assert_called_once_with()
        playwright.stop.assert_called_once_with()

    @patch("scripts.validate_shopee_visible.BrowserManager")
    @patch("builtins.input", return_value="")
    def test_visible_validation_allows_manual_login(
        self,
        input_mock,
        browser_manager_class,
    ):
        page = browser_manager_class.return_value.new_page.return_value
        validate_shopee_visible.main(["--prepare-login"])

        call = browser_manager_class.call_args
        self.assertFalse(call.kwargs["headless"])
        self.assertEqual(
            call.kwargs["user_data_dir"],
            validate_shopee_visible.SHOPEE_PROFILE_PATH,
        )
        input_mock.assert_called_once()
        page.goto.assert_called_once()
        browser_manager_class.return_value.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
