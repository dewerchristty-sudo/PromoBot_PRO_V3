import unittest
from unittest.mock import Mock, patch

from src.core.notifier import Notifier
from src.scraper import Parser
from src.stores.amazon import Amazon
from src.stores.mercado_livre import MercadoLivre
from src.stores.shopee import Shopee
from src.ui.affiliate_links_page import AffiliateLinksPage


class PriceConsistencyThreeStoresTest(unittest.TestCase):

    def test_parser_aceita_formatos_br_e_api_sem_alterar_valor(self):
        cases = {
            "R$ 999,90": 999.90,
            "1.299,90": 1299.90,
            "1299.90": 1299.90,
            "25,990.00": 25990.00,
            10599.9: 10599.90,
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(Parser.price_to_float(raw), expected)

    def test_formatacao_brasileira_com_milhar(self):
        self.assertEqual(Parser.format_brl(999.9), "999,90")
        self.assertEqual(Parser.format_brl(1299.9), "1.299,90")
        self.assertEqual(Parser.format_brl(25990), "25.990,00")
        self.assertEqual(
            Parser.format_brl(10599.9, include_symbol=True),
            "R$ 10.599,90",
        )

    def test_mercado_livre_com_e_sem_preco_anterior(self):
        store = MercadoLivre.__new__(MercadoLivre)
        common = """
          <h1 class="ui-pdp-title">Notebook ML</h1>
          <div class="ui-pdp-price__second-line">
            <span class="andes-money-amount">
              <span class="andes-money-amount__fraction">1.299</span>
              <span class="andes-money-amount__cents">90</span>
            </span>
          </div>
          <meta property="og:image" content="https://example.com/ml.jpg">
        """
        with_old = common + """
          <span class="andes-money-amount andes-money-amount--previous">
            <span class="andes-money-amount__fraction">1.599</span>
            <span class="andes-money-amount__cents">90</span>
          </span>
        """
        product = store.product_data_from_html(with_old, "https://ml/MLB-1")
        self.assertEqual(product["preco"], "1.299,90")
        self.assertEqual(product["preco_antigo"], "1.599,90")
        without = store.product_data_from_html(common, "https://ml/MLB-1")
        self.assertNotIn("preco_antigo", without)

    def test_amazon_com_e_sem_preco_anterior(self):
        store = Amazon.__new__(Amazon)
        common = """
          <span id="productTitle">Notebook Amazon</span>
          <span class="a-price">
            <span class="a-offscreen">R$ 10.599,90</span>
          </span>
          <img id="landingImage" src="https://example.com/amz.jpg">
        """
        with_old = common + """
          <span class="a-price a-text-price">
            <span class="a-offscreen">R$ 12.999,90</span>
          </span>
        """
        product = store.product_data_from_html(with_old, "https://amz/dp/A")
        self.assertEqual(product["preco"], "10.599,90")
        self.assertEqual(product["preco_antigo"], "12.999,90")
        without = store.product_data_from_html(common, "https://amz/dp/A")
        self.assertNotIn("preco_antigo", without)

    def test_shopee_com_e_sem_preco_anterior(self):
        from bs4 import BeautifulSoup

        with_old = BeautifulSoup(
            '<script>{"price":129990000,'
            '"price_before_discount":159990000}</script>',
            "lxml",
        )
        self.assertEqual(
            Shopee.prices_from_page(with_old),
            ("1.299,90", "1.599,90"),
        )
        without = BeautifulSoup(
            '<script>{"price":2599000000}</script>',
            "lxml",
        )
        self.assertEqual(
            Shopee.prices_from_page(without),
            ("25.990,00", ""),
        )

    def test_link_curto_shopee_e_aceito_para_recuperacao(self):
        page = AffiliateLinksPage.__new__(AffiliateLinksPage)
        page.database = Mock()
        page.database.referencia_produto_link.return_value = ""
        short = "https://s.shopee.com.br/AbCd123"
        self.assertEqual(page.normalize_manual_product_link(short), short)

    @patch("src.stores.shopee.BrowserManager")
    def test_link_curto_shopee_recupera_produto_completo(self, manager_cls):
        page = Mock()
        page.url = "https://shopee.com.br/produto-exemplo-i.123456789.987654321"
        page.content.return_value = """
            <html>
              <head>
                <meta property="og:title" content="Produto Shopee válido">
                <meta property="og:image" content="https://cdn.example/item.jpg">
                <meta property="product:price:amount" content="1299.90">
              </head>
              <body>
                <script>{"price_before_discount":159990000}</script>
              </body>
            </html>
        """
        page.evaluate.return_value = None
        manager_cls.return_value.new_page.return_value = page

        product = Shopee().product_from_url("https://s.shopee.com.br/AbCdEf123")

        self.assertIsNotNone(product)
        self.assertEqual(product["titulo"], "Produto Shopee válido")
        self.assertEqual(product["preco"], "1.299,90")
        self.assertEqual(product["preco_antigo"], "1.599,90")
        self.assertEqual(product["imagem"], "https://cdn.example/item.jpg")
        self.assertEqual(product["link"], "https://s.shopee.com.br/AbCdEf123")

    def test_whatsapp_mantem_mensagem_e_formata_milhar(self):
        notifier = Notifier()
        message = notifier.format_alert({
            "titulo": "Notebook",
            "loja": "Amazon",
            "preco_valor": 10599.9,
            "preco_antigo": 12999.9,
            "link": "https://example.com",
            "imagem": "https://example.com/image.jpg",
        })
        self.assertIn("De: R$ 12.999,90", message)
        self.assertIn("Por: R$ 10.599,90", message)


if __name__ == "__main__":
    unittest.main()
