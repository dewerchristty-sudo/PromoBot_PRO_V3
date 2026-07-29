import logging
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.core.single_cycle_runner import (
    SingleCycleConfig,
    SingleCycleRunner,
)
from src.core.store_manager import StoreManager
from src.stores.amazon import Amazon, AmazonSearchUnavailable


VALID_CARD = """
<div data-component-type="s-search-result" data-asin="B0ABC12345">
  <h2><a href="/dp/B0ABC12345"><span>Air Fryer Segura</span></a></h2>
  <span class="a-price"><span class="a-offscreen">R$ 299,90</span></span>
  <img src="https://images.invalid/fryer.jpg">
</div>
"""


class FakeResponse:

    def __init__(self, status):
        self.status = status


class FakePage:

    def __init__(self, html, status=200, title="Amazon.com.br : air fryer"):
        self.html = html
        self.status = status
        self.page_title = title
        self.closed = False
        self.waited_selector = ""

    def goto(self, _url, **_kwargs):
        return FakeResponse(self.status)

    def title(self):
        return self.page_title

    def content(self):
        return self.html

    def wait_for_selector(self, selector, timeout):
        self.waited_selector = selector
        self.waited_timeout = timeout
        return None

    def close(self):
        self.closed = True


class FakeBrowserManager:

    def __init__(self, page):
        self.page = page
        self.closed = False

    def new_page(self):
        return self.page

    def close(self):
        self.closed = True


def search_html(cards=VALID_CARD, extra=""):
    return (
        "<html><head><title>Amazon</title></head>"
        "<body><div id='search'><div class='s-main-slot'>"
        f"{cards}</div></div>{extra}</body></html>"
    )


class AmazonSearchDiagnosticsTest(unittest.TestCase):

    def store(self, html, status=200, title="Amazon.com.br : air fryer"):
        page = FakePage(html, status=status, title=title)
        manager = FakeBrowserManager(page)
        return Amazon(manager), page, manager

    def test_http_200_with_products(self):
        store, page, manager = self.store(search_html())
        products = store.search("air fryer")
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0]["titulo"], "Air Fryer Segura")
        self.assertEqual(
            page.waited_selector,
            Amazon.SEARCH_RESULT_SELECTOR,
        )
        self.assertTrue(page.closed)
        self.assertTrue(manager.closed)

    def test_http_200_legitimate_empty_results(self):
        html = search_html(
            cards="",
            extra="<p>Não encontramos resultados para sua busca</p>",
        )
        store, _page, _manager = self.store(html)
        self.assertEqual(store.search("produto inexistente"), [])

    def test_http_429_and_503_raise_sanitized_error(self):
        for status in (429, 503):
            with self.subTest(status=status):
                store, _page, _manager = self.store(
                    "<html>erro</html>",
                    status=status,
                )
                with (
                    self.assertLogs(
                        "src.stores.amazon",
                        level=logging.WARNING,
                    ) as captured,
                    self.assertRaisesRegex(
                        AmazonSearchUnavailable,
                        rf"HTTP {status}",
                    ) as raised,
                ):
                    store.search("air fryer")
                message = str(raised.exception)
                self.assertNotIn("<html>", message)
                self.assertNotIn("https://", message)
                diagnostic = " ".join(captured.output)
                self.assertIn(f"status={status}", diagnostic)
                self.assertIn(
                    f"classification=HTTP_{status}",
                    diagnostic,
                )
                self.assertIn("raw_cards=0", diagnostic)
                self.assertIn("accepted=0", diagnostic)

    def test_amazon_error_title_is_rejected(self):
        store, _page, _manager = self.store(
            "<html><body>erro</body></html>",
            title="Amazon.com.br Algo deu errado",
        )
        with self.assertRaisesRegex(
            AmazonSearchUnavailable,
            "pagina de erro",
        ):
            store.search("air fryer")

    def test_robot_check_is_rejected(self):
        store, _page, _manager = self.store(
            "<html><body>Robot Check</body></html>",
            title="Robot Check",
        )
        with self.assertRaisesRegex(
            AmazonSearchUnavailable,
            "Robot Check",
        ):
            store.search("air fryer")

    def test_captcha_is_rejected(self):
        html = (
            "<html><body><form action='/errors/validateCaptcha'>"
            "<input id='captchacharacters'></form></body></html>"
        )
        store, _page, _manager = self.store(html)
        with self.assertRaisesRegex(
            AmazonSearchUnavailable,
            "captcha",
        ):
            store.search("air fryer")

    def test_small_incomplete_html_is_rejected(self):
        store, _page, _manager = self.store("<html><body></body></html>")
        with self.assertRaisesRegex(
            AmazonSearchUnavailable,
            "HTML incompleto",
        ):
            store.search("air fryer")

    def test_missing_minimum_search_structure_is_rejected(self):
        html = "<html><body>" + ("conteudo " * 500) + "</body></html>"
        store, _page, _manager = self.store(html)
        with self.assertRaisesRegex(
            AmazonSearchUnavailable,
            "estrutura de busca ausente",
        ):
            store.search("air fryer")

    def test_primary_selector_is_preferred(self):
        from bs4 import BeautifulSoup

        cards, selector = Amazon.search_cards(
            BeautifulSoup(search_html(), "lxml")
        )
        self.assertEqual(len(cards), 1)
        self.assertEqual(selector, Amazon.SEARCH_RESULT_SELECTOR)

    def test_alternative_selector_is_supported(self):
        from bs4 import BeautifulSoup

        alternative = VALID_CARD.replace(
            'data-component-type="s-search-result" ',
            'class="s-result-item" ',
        )
        cards, selector = Amazon.search_cards(
            BeautifulSoup(search_html(alternative), "lxml")
        )
        self.assertEqual(len(cards), 1)
        self.assertEqual(selector, "div.s-result-item[data-asin]")

    def test_missing_fields_are_counted_and_discarded(self):
        no_title = VALID_CARD.replace(
            "<h2><a href=\"/dp/B0ABC12345\"><span>Air Fryer Segura"
            "</span></a></h2>",
            "",
        )
        no_link = VALID_CARD.replace('href="/dp/B0ABC12345"', 'href="#"')
        no_price = VALID_CARD.replace(
            '<span class="a-price"><span class="a-offscreen">'
            "R$ 299,90</span></span>",
            "",
        )
        store, _page, _manager = self.store(
            search_html(no_title + no_link + no_price + VALID_CARD)
        )
        with self.assertLogs(
            "src.stores.amazon",
            level=logging.INFO,
        ) as captured:
            products = store.search("air fryer")
        self.assertEqual(len(products), 1)
        joined = " ".join(captured.output)
        self.assertIn("missing_title=1", joined)
        self.assertIn("missing_link=1", joined)
        self.assertIn("missing_price=1", joined)
        self.assertIn("accepted=1", joined)

    def test_individual_card_exception_is_counted(self):
        store, _page, _manager = self.store(
            search_html(VALID_CARD + VALID_CARD)
        )
        original = Amazon.previous_price_from_soup
        calls = {"count": 0}

        def sometimes_fails(*args, **kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise ValueError("falha simulada")
            return original(*args, **kwargs)

        with (
            patch.object(
                Amazon,
                "previous_price_from_soup",
                side_effect=sometimes_fails,
            ),
            self.assertLogs(
                "src.stores.amazon",
                level=logging.INFO,
            ) as captured,
        ):
            products = store.search("air fryer")
        self.assertEqual(len(products), 1)
        self.assertIn(
            "extraction_errors=1",
            " ".join(captured.output),
        )
        self.assertNotIn("falha simulada", " ".join(captured.output))

    def test_card_analysis_limit_remains_twenty(self):
        store, _page, _manager = self.store(
            search_html(VALID_CARD * 25)
        )
        with self.assertLogs(
            "src.stores.amazon",
            level=logging.INFO,
        ) as captured:
            products = store.search("air fryer")
        self.assertEqual(len(products), 20)
        self.assertIn("analyzed=20", " ".join(captured.output))

    def test_store_manager_reports_amazon_error(self):
        store, _page, _manager = self.store(
            "<html>erro</html>",
            status=503,
        )
        messages = []
        manager = StoreManager(
            progress_callback=messages.append,
            enabled_stores=[],
            offer_shadow_enabled=False,
        )
        manager.stores = [store]
        self.assertEqual(manager.search_all("air fryer"), [])
        self.assertTrue(any(
            message.startswith("[ERRO] Amazon:")
            and "HTTP 503" in message
            for message in messages
        ))

    def test_single_cycle_lists_amazon_in_stores_with_error(self):
        store, _page, _manager = self.store(
            "<html>erro</html>",
            status=503,
        )

        def manager_factory(
            progress_callback=None,
            enabled_stores=None,
            offer_shadow_enabled=None,
        ):
            manager = StoreManager(
                progress_callback=progress_callback,
                enabled_stores=[],
                offer_shadow_enabled=offer_shadow_enabled,
            )
            manager.stores = [store]
            return manager

        with tempfile.TemporaryDirectory() as temporary:
            config = SingleCycleConfig.create(
                term="air fryer",
                stores=["amazon"],
                destination="5511999999999",
                database_path=Path(temporary) / "temporary.db",
            )
            with patch(
                "src.core.single_cycle_runner.StoreManager",
                side_effect=manager_factory,
            ):
                result = SingleCycleRunner(config).run()
        self.assertEqual(result.stores_with_error, ("Amazon",))
        self.assertEqual(result.collected_count, 0)
        self.assertEqual(result.transport_calls, 0)


if __name__ == "__main__":
    unittest.main()
