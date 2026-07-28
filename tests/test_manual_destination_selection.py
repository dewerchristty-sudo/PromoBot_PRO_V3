import os
import unittest
from unittest.mock import Mock, patch

from src.ui.affiliate_links_page import AffiliateLinksPage


class FakeVariable:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class ManualDestinationSelectionTest(unittest.TestCase):

    def page(self):
        page = AffiliateLinksPage.__new__(AffiliateLinksPage)
        page.selected_destination = FakeVariable()
        page.review_destination_button = Mock()
        page.house_destination_button = Mock()
        return page

    def test_seleciona_revisao_promobot(self):
        page = self.page()
        page.select_manual_destination("review")

        self.assertEqual(page.selected_destination.get(), "review")
        review = page.review_destination_button.configure.call_args.kwargs
        house = page.house_destination_button.configure.call_args.kwargs
        self.assertEqual(review["fg_color"], page.DESTINATION_SELECTED_COLOR)
        self.assertEqual(house["fg_color"], page.DESTINATION_DEFAULT_COLOR)

    def test_seleciona_casa_ofertas_e_desmarca_revisao(self):
        page = self.page()
        page.select_manual_destination("review")
        page.select_manual_destination("house")

        self.assertEqual(page.selected_destination.get(), "house")
        review = page.review_destination_button.configure.call_args.kwargs
        house = page.house_destination_button.configure.call_args.kwargs
        self.assertEqual(review["fg_color"], page.DESTINATION_DEFAULT_COLOR)
        self.assertEqual(house["fg_color"], page.DESTINATION_SELECTED_COLOR)

    @patch("src.ui.affiliate_links_page.messagebox")
    def test_bloqueia_sem_destino_antes_de_salvar(self, messagebox):
        page = self.page()
        page.save_selected_link = Mock()

        page.save_and_notify()

        page.save_selected_link.assert_not_called()
        messagebox.showwarning.assert_called_once_with(
            "Selecione o destino",
            "Selecione Revisão PromoBot ou Casa & Ofertas antes de enviar.",
        )

    def test_localiza_destinos_somente_na_configuracao(self):
        page = self.page()
        with patch.dict(os.environ, {
            "WHATSAPP_REVIEW_GROUP": "review@g.us",
            "WHATSAPP_GROUP_CASA_ENXOVAL": "house@g.us",
        }):
            page.select_manual_destination("review")
            self.assertEqual(
                page.selected_destination_config(),
                ("review", "Revisão PromoBot", "review@g.us"),
            )
            page.select_manual_destination("house")
            self.assertEqual(
                page.selected_destination_config(),
                ("house", "Casa & Ofertas", "house@g.us"),
            )

    def test_envia_somente_para_destino_escolhido_e_registra_historico(self):
        page = self.page()
        page.database = Mock()
        page.notifier = Mock()
        page.notifier.whatsapp_configured.return_value = True
        page.notifier.has_affiliate_link.return_value = True
        page.notifier.verified_whatsapp_image.return_value = (
            "https://example.com/image.jpg"
        )
        page.notifier.format_alert.return_value = "mensagem original"
        page.notifier.affiliate_link.return_value = "https://affiliate"
        product = {
            "titulo": "Produto",
            "loja": "Mercado Livre",
            "link": "https://original",
        }

        result = page.send_to_selected_destination(
            product,
            "Casa & Ofertas",
            "house@g.us",
        )

        self.assertTrue(result.startswith("Enviado por:"))
        page.notifier.send_whatsapp_message.assert_called_once_with(
            "mensagem original",
            "https://example.com/image.jpg",
            "house@g.us",
        )
        page.database.registrar_envio.assert_called_once()
        self.assertEqual(
            page.database.registrar_envio.call_args.args[-1],
            "house@g.us",
        )
        self.assertNotIn(
            "review@g.us",
            page.notifier.send_whatsapp_message.call_args.args,
        )

    @patch("src.ui.affiliate_links_page.messagebox")
    def test_limpa_selecao_somente_apos_sucesso(self, messagebox):
        page = self.page()
        page.select_manual_destination("house")

        self.assertTrue(page.show_manual_destination_result(
            "Enviado por: WhatsApp — Casa & Ofertas."
        ))
        self.assertEqual(page.selected_destination.get(), "")

        page.select_manual_destination("review")
        self.assertFalse(page.show_manual_destination_result("Falha"))
        self.assertEqual(page.selected_destination.get(), "review")


if __name__ == "__main__":
    unittest.main()
