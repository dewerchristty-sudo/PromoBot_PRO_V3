import unittest

from src.ui.affiliate_links_page import AffiliateLinksPage


class AffiliateLinksPageTest(unittest.TestCase):

    def page(self):
        page = AffiliateLinksPage.__new__(AffiliateLinksPage)
        page.database = type(
            "DatabaseStub",
            (),
            {"referencia_produto_link": staticmethod(lambda link: "B012345678" if "/dp/B012345678" in link else "")},
        )()
        return page

    def test_aceita_link_curto_oficial_link_amazon(self):

        page = AffiliateLinksPage.__new__(AffiliateLinksPage)
        product = {
            "loja": "Amazon",
            "link": "https://www.amazon.com.br/dp/B012345678",
        }

        page.validate_link_format(product, "https://link.amazon/A0frIDpYS")

    def test_identifica_loja_pelo_link_original(self):

        self.assertEqual(
            AffiliateLinksPage.identify_store_by_link(
                "https://www.amazon.com.br/dp/B012345678"
            ),
            "amazon",
        )
        self.assertEqual(
            AffiliateLinksPage.identify_store_by_link(
                "https://produto.mercadolivre.com.br/MLB-123"
            ),
            "mercado livre",
        )
        self.assertEqual(
            AffiliateLinksPage.identify_store_by_link(
                "https://shopee.com.br/produto-i.1.2"
            ),
            "shopee",
        )

    def test_rejeita_link_afiliado_de_outra_loja_no_cadastro_manual(self):

        page = AffiliateLinksPage.__new__(AffiliateLinksPage)
        product = {
            "loja": "Amazon",
            "link": "https://www.amazon.com.br/dp/B012345678",
        }

        with self.assertRaisesRegex(ValueError, "Dominio invalido para amazon"):
            page.validate_link_format(product, "https://s.shopee.com.br/abc123")

    def test_normaliza_link_de_produto_amazon(self):

        page = self.page()

        self.assertEqual(
            page.normalize_manual_product_link(
                "https://www.amazon.com.br/Produto/dp/B012345678/ref=abc?tag=teste"
            ),
            "https://www.amazon.com.br/dp/B012345678",
        )

    def test_rejeita_carrinho_amazon_como_link_original(self):

        page = self.page()

        with self.assertRaisesRegex(ValueError, "diretamente a pagina do produto"):
            page.normalize_manual_product_link(
                "https://www.amazon.com.br/gp/cart/view.html?linkId=abc"
            )

    def test_monta_produto_totalmente_manual(self):

        page = AffiliateLinksPage.__new__(AffiliateLinksPage)
        page.manual_only = True
        field = lambda value: type("Field", (), {"get": lambda self: value})()
        page.manual_title = field("Produto informado pelo usuario")
        page.manual_price = field("149,90")
        page.manual_image = field("https://images.example/produto.jpg")
        page.manual_category = field("Smartphones e Tecnologia")

        product = page.manual_product_data(
            "https://www.amazon.com.br/dp/B012345678"
        )

        self.assertEqual(product["titulo"], "Produto informado pelo usuario")
        self.assertEqual(product["categoria_manual"], "smartphones_tecnologia")


if __name__ == "__main__":
    unittest.main()
