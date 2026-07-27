import unittest
from unittest.mock import Mock, patch

from src.core.notifier import Notifier
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

    def test_normaliza_recomendacao_mercado_livre_com_wid(self):

        page = AffiliateLinksPage.__new__(AffiliateLinksPage)
        page.database = type(
            "DatabaseStub",
            (),
            {
                "referencia_produto_link": staticmethod(
                    lambda link: "MLB4580504787"
                    if "wid=MLB4580504787" in link
                    else ""
                )
            },
        )()

        self.assertEqual(
            page.normalize_manual_product_link(
                "https://www.mercadolivre.com.br/navigation/recos"
                "?item_id=abc&wid=MLB4580504787&sid=recos"
            ),
            "https://produto.mercadolivre.com.br/MLB-4580504787",
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

    def test_monta_shopee_manual_apos_bloqueio(self):

        page = AffiliateLinksPage.__new__(AffiliateLinksPage)
        page.manual_only = False
        page.entry_mode = "Cadastro manual"
        link = "https://shopee.com.br/produto-i.1.2"
        page.shopee_manual_link = link
        field = lambda value: type("Field", (), {"get": lambda self: value})()
        page.manual_title = field("Produto Shopee informado pelo usuario")
        page.manual_price = field("89,90")
        page.manual_image = field("https://down-br.img.susercontent.com/file/imagem")
        page.manual_category = field("Smartphones e Tecnologia")

        product = page.manual_product_data(link)

        self.assertEqual(product["loja"], "Shopee")
        self.assertEqual(product["link"], link)
        self.assertEqual(product["titulo"], "Produto Shopee informado pelo usuario")

    def test_monta_mercado_livre_manual_apos_bloqueio(self):

        page = AffiliateLinksPage.__new__(AffiliateLinksPage)
        page.manual_only = False
        page.entry_mode = "Cadastro manual"
        link = "https://produto.mercadolivre.com.br/MLB-4580504787"
        page.shopee_manual_link = link
        page.manual_fallback_store = "Mercado Livre"
        field = lambda value: type("Field", (), {"get": lambda self: value})()
        page.manual_title = field("Produto Mercado Livre")
        page.manual_price = field("89,90")
        page.manual_old_price = field("129,90")
        page.manual_image = field("https://http2.mlstatic.com/produto.jpg")
        page.manual_category = field("Smartphones e Tecnologia")

        product = page.manual_product_data(link)

        self.assertEqual(product["loja"], "Mercado Livre")
        self.assertEqual(product["preco"], "89,90")
        self.assertEqual(product["preco_antigo"], "129,90")

    def test_shopee_bloqueada_exige_dados_sem_tentar_importacao(self):

        page = AffiliateLinksPage.__new__(AffiliateLinksPage)
        page.manual_only = False
        page.entry_mode = "Cadastro manual"
        link = "https://shopee.com.br/produto-i.1.2"
        page.shopee_manual_link = link
        field = lambda value: type("Field", (), {"get": lambda self: value})()
        page.manual_title = field("")
        page.manual_price = field("")
        page.manual_image = field("")
        page.manual_category = field("Selecione a categoria")

        with self.assertRaisesRegex(ValueError, "Complete os dados manuais"):
            page.manual_product_data(link)

    def shopee_manual_page(self, current_price, old_price):

        page = AffiliateLinksPage.__new__(AffiliateLinksPage)
        page.manual_only = False
        page.entry_mode = "Cadastro manual"
        link = "https://shopee.com.br/produto-i.1.2"
        page.shopee_manual_link = link
        field = lambda value: type("Field", (), {"get": lambda self: value})()
        page.manual_title = field("Produto Shopee")
        page.manual_price = field(current_price)
        page.manual_old_price = field(old_price)
        page.manual_image = field("https://example.com/produto.jpg")
        page.manual_category = field("Smartphones e Tecnologia")
        return page, link

    def test_preco_anterior_vazio_e_permitido(self):

        page, link = self.shopee_manual_page("48,90", "")

        product = page.manual_product_data(link)

        self.assertEqual(product["preco_antigo"], "")

    def test_rejeita_preco_anterior_invalido(self):

        page, link = self.shopee_manual_page("48,90", "invalido")

        with self.assertRaisesRegex(ValueError, "preco anterior valido"):
            page.manual_product_data(link)

    def test_rejeita_preco_anterior_menor_ou_igual_ao_atual(self):

        page, link = self.shopee_manual_page("48,90", "48,90")

        with self.assertRaisesRegex(ValueError, "maior que o preco atual"):
            page.manual_product_data(link)

    def test_monta_produto_manual_com_preco_anterior(self):

        page, link = self.shopee_manual_page("48,90", "79,90")

        product = page.manual_product_data(link)

        self.assertEqual(product["preco"], "48,90")
        self.assertEqual(product["preco_antigo"], "79,90")

    @patch("src.ui.affiliate_links_page.messagebox.showinfo")
    @patch("src.ui.affiliate_links_page.messagebox.showerror")
    def test_produto_antigo_nao_sobrescreve_formulario_shopee(
        self,
        showerror,
        _showinfo,
    ):

        page, link = self.shopee_manual_page("44,98", "79,90")
        page.manual_title = type(
            "Field",
            (),
            {"get": lambda self: "Produto manual"},
        )()
        page.manual_image = type(
            "Field",
            (),
            {"get": lambda self: "https://example.com/manual.jpg"},
        )()
        page.save_selected_link = Mock(return_value={
            "loja": "Shopee",
            "link": link,
        })
        stored = {
            "id": 10,
            "loja": "Shopee",
            "titulo": "Produto antigo",
            "preco": "1980,00",
            "preco_valor": 1980.0,
            "maior_preco": 1980.0,
            "link": link,
            "imagem": "https://example.com/antiga.jpg",
        }
        database = Mock()
        database.buscar_produto_por_link.side_effect = [stored, stored]
        database.produto_ja_notificado.return_value = False
        page.database = database
        page.status = Mock()
        page.update_idletasks = Mock()
        page.load_pending = Mock()
        page.trace_manual_product = Mock()
        page.affiliate_link = type(
            "Field",
            (),
            {"get": lambda self: "https://s.shopee.com.br/teste"},
        )()
        page.tracking_label = type(
            "Field",
            (),
            {"get": lambda self: "teste"},
        )()
        notifier = Mock()
        notifier.prepare_whatsapp_image.return_value = b"jpeg"
        notifier.partition_offer_quality.return_value = ([{}], [], [])
        captured = {}

        def send_alerts(products, **_kwargs):
            captured.update(products[0])
            return "Enviado por: WhatsApp"

        notifier.send_alerts.side_effect = send_alerts
        page.notifier = notifier

        page.save_and_notify()

        self.assertEqual(captured["preco"], "44,98")
        self.assertEqual(captured["preco_valor"], 44.98)
        self.assertEqual(captured["preco_antigo"], "79,90")
        message = Notifier().format_alert(captured)
        self.assertIn("De: R$ 79,90", message)
        self.assertIn("Por: R$ 44,98", message)
        self.assertIn("R$ 34,92", message)
        self.assertIn("desconto de 43,7%", message)
        showerror.assert_not_called()


if __name__ == "__main__":
    unittest.main()
