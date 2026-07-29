import asyncio
import unittest
from unittest.mock import Mock, patch

from src.stores.amazon import Amazon
from src.stores.mercado_livre import MercadoLivre
from src.stores.shopee import Shopee


MERCADO_LIVRE_PROMOTION_HTML = """
<h1 class="ui-pdp-title">Produto Mercado Livre</h1>
<div class="ui-pdp-price__original-value">
  <span class="andes-money-amount andes-money-amount--previous">
    <span class="andes-money-amount__fraction">1.599</span>
    <span class="andes-money-amount__cents">90</span>
  </span>
</div>
<div class="ui-pdp-price__second-line">
  <span class="andes-money-amount">
    <span class="andes-money-amount__fraction">1.299</span>
    <span class="andes-money-amount__cents">90</span>
  </span>
</div>
<meta property="og:image" content="https://example.com/ml.jpg">
"""


class MercadoLivreImportStabilityTest(unittest.TestCase):

    def setUp(self):
        self.store = MercadoLivre.__new__(MercadoLivre)

    def test_produto_com_promocao_captura_precos_atual_e_anterior(self):
        product = self.store.product_data_from_html(
            MERCADO_LIVRE_PROMOTION_HTML,
            "https://produto.mercadolivre.com.br/MLB-123456",
        )

        self.assertEqual(product["preco"], "1.299,90")
        self.assertEqual(product["preco_antigo"], "1.599,90")

    def test_produto_sem_promocao_nao_inventa_preco_anterior(self):
        html = MERCADO_LIVRE_PROMOTION_HTML.replace(
            '<div class="ui-pdp-price__original-value">',
            '<div class="ausente">',
        ).replace(
            "andes-money-amount andes-money-amount--previous",
            "valor-nao-anterior",
        )
        product = self.store.product_data_from_html(
            html,
            "https://produto.mercadolivre.com.br/MLB-123456",
        )

        self.assertEqual(product["preco"], "1.299,90")
        self.assertNotIn("preco_antigo", product)

    def test_json_ld_e_meta_tags_sao_fallbacks_validos(self):
        product = self.store.product_data_from_html(
            """
            <script type="application/ld+json">
            {"@type":"Product","name":"Produto JSON",
             "image":"https://example.com/json.jpg",
             "offers":{"price":"299.90","highPrice":"399.90"}}
            </script>
            """,
            "https://www.mercadolivre.com.br/p/MLB123456",
        )

        self.assertEqual(product["preco"], "299,90")
        self.assertEqual(product["preco_antigo"], "399,90")

    def test_estado_json_interno_e_utilizado_como_fallback(self):
        product = self.store.product_data_from_html(
            """
            <script>
            {"item":{"id":"MLB123456","title":"Produto interno",
             "price":219.90,"original_price":279.90,
             "image":"https://example.com/internal.jpg"}}
            </script>
            """,
            "https://www.mercadolivre.com.br/p/MLB123456",
        )

        self.assertEqual(product["titulo"], "Produto interno")
        self.assertEqual(product["preco"], "219,90")
        self.assertEqual(product["preco_antigo"], "279,90")

    def test_link_meli_la_usa_url_final_do_redirect_get(self):
        page = Mock()
        page.url = "https://produto.mercadolivre.com.br/MLB-123456"
        page.content.return_value = MERCADO_LIVRE_PROMOTION_HTML
        page.title.return_value = "Produto"
        page.goto.return_value.status = 200
        manager = Mock()
        manager.new_page.return_value = page
        store = MercadoLivre(browser_manager=manager)

        product = store.product_from_url("https://meli.la/abc123")

        self.assertEqual(product["link"], page.url)
        page.goto.assert_called_once_with(
            "https://meli.la/abc123",
            wait_until="domcontentloaded",
            timeout=60000,
        )
        page.close.assert_called_once()
        manager.close.assert_called_once()

    @patch("src.stores.mercado_livre.requests.get")
    def test_link_mlb_antigo_usa_fallback_por_identificador(self, get):
        response = Mock()
        response.json.return_value = {
            "title": "Produto ainda ativo",
            "price": 99.90,
            "original_price": 129.90,
            "secure_thumbnail": "http://example.com/item.jpg",
        }
        get.return_value = response

        product = self.store.product_data_from_api(
            "https://produto.mercadolivre.com.br/MLB-987654",
        )

        self.assertEqual(product["preco"], "99,90")
        self.assertEqual(product["preco_antigo"], "129,90")
        get.assert_called_once()


class AmazonImportStabilityTest(unittest.TestCase):

    def setUp(self):
        self.store = Amazon.__new__(Amazon)

    def product(self, price_html, previous_html=""):
        return self.store.product_data_from_html(
            f"""
            <span id="productTitle">Produto Amazon</span>
            {price_html}
            {previous_html}
            <img id="landingImage" src="https://example.com/amazon.jpg">
            """,
            "https://www.amazon.com.br/dp/B000TESTE",
        )

    def test_preco_normal(self):
        product = self.product(
            '<span id="price_inside_buybox">R$ 149,90</span>'
        )
        self.assertEqual(product["preco"], "149,90")

    def test_preco_promocional_prioriza_price_to_pay(self):
        product = self.product(
            """
            <div id="corePrice_feature_div">
              <span class="a-price priceToPay">
                <span class="a-offscreen">R$ 79,90</span>
              </span>
            </div>
            """,
            """
            <div id="basisPrice"><span class="a-price a-text-price">
              <span class="a-offscreen">R$ 129,90</span>
            </span></div>
            """,
        )
        self.assertEqual(product["preco"], "79,90")
        self.assertEqual(product["preco_antigo"], "129,90")

    def test_sem_desconto_nao_inventa_preco_anterior(self):
        product = self.product(
            '<span id="newBuyBoxPrice">R$ 89,90</span>'
        )
        self.assertNotIn("preco_antigo", product)

    def test_nao_captura_preco_parcelado(self):
        product = self.product(
            """
            <div id="installment-price">
              10 parcelas de
              <span class="a-price"><span class="a-offscreen">
                R$ 19,99
              </span></span>
            </div>
            <span id="price_inside_buybox">R$ 189,90</span>
            """
        )
        self.assertEqual(product["preco"], "189,90")


class FakeShopeePage:
    def __init__(self):
        self.url = "https://shopee.com.br/produto-i.1.2"
        self.closed = False

    def goto(self, *_args, **_kwargs):
        return None

    def wait_for_timeout(self, _timeout):
        return None

    def content(self):
        return """
        <meta property="og:title" content="Produto Shopee">
        <meta property="og:image" content="https://example.com/shopee.jpg">
        <meta property="product:price:amount" content="49.90">
        """

    def evaluate(self, _script):
        return []

    def close(self):
        self.closed = True


class FakeShopeeManager:
    def __init__(self):
        self.pages = []
        self.close_calls = 0

    def new_page(self, stealth=True):
        page = FakeShopeePage()
        self.pages.append(page)
        return page

    def close(self):
        self.close_calls += 1


class IsolatedShopee(Shopee):
    instances = []

    def __init__(self, browser_manager=None):
        manager = browser_manager or FakeShopeeManager()
        super().__init__(manager)
        self.instances.append(self)


class ShopeeSequentialImportTest(unittest.TestCase):

    def setUp(self):
        IsolatedShopee.instances.clear()

    def test_vinte_importacoes_consecutivas_fecham_todas_as_paginas(self):
        manager = FakeShopeeManager()
        store = IsolatedShopee(manager)

        products = [
            store.product_from_url(
                f"https://shopee.com.br/produto-i.1.{index}"
            )
            for index in range(20)
        ]

        self.assertEqual(len(products), 20)
        self.assertEqual(len(manager.pages), 20)
        self.assertTrue(all(page.closed for page in manager.pages))
        self.assertEqual(manager.close_calls, 0)

        store.close()
        self.assertEqual(manager.close_calls, 1)

    def test_chamada_em_asyncio_isola_sync_api_e_fecha_contexto(self):
        store = IsolatedShopee(FakeShopeeManager())

        async def import_inside_loop():
            return store.product_from_url(
                "https://shopee.com.br/produto-i.1.99"
            )

        product = asyncio.run(import_inside_loop())

        self.assertEqual(product["titulo"], "Produto Shopee")
        isolated = IsolatedShopee.instances[-1]
        self.assertIsNot(isolated, store)
        self.assertTrue(all(page.closed for page in isolated.browser_manager.pages))
        self.assertEqual(isolated.browser_manager.close_calls, 1)


if __name__ == "__main__":
    unittest.main()
