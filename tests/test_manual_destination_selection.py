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
        page.send_personal_copy = FakeVariable(False)
        page.review_destination_button = Mock()
        page.house_destination_button = Mock()
        page.personal_destination_button = Mock()
        page.personal_copy_checkbox = Mock()
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
            "Selecione o destino da mensagem.",
        )

    def test_segundo_clique_desmarca_destino(self):
        page = self.page()

        page.select_manual_destination("review")
        page.select_manual_destination("review")

        self.assertEqual(page.selected_destination.get(), "")

    def test_meu_whatsapp_e_destino_exclusivo(self):
        page = self.page()

        page.select_manual_destination("house")
        page.select_manual_destination("personal")

        self.assertEqual(page.selected_destination.get(), "personal")
        self.assertFalse(page.send_personal_copy.get())
        self.assertEqual(
            page.personal_destination_button.configure.call_args.kwargs[
                "fg_color"
            ],
            page.DESTINATION_SELECTED_COLOR,
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
            with patch.dict(
                os.environ,
                {"WHATSAPP_PERSONAL_ALERT_PHONES": "5511999999999"},
            ):
                page.select_manual_destination("personal")
                self.assertEqual(
                    page.selected_destination_config(),
                    ("personal", "Meu WhatsApp", "5511999999999"),
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

    def test_copia_adicional_exige_consentimento_explicito(self):
        page = self.page()
        page.database = Mock()
        page.notifier = Mock()
        page.notifier.whatsapp_configured.return_value = True
        page.notifier.evolution_configured.return_value = False
        page.notifier.has_affiliate_link.return_value = True
        page.notifier.verified_whatsapp_image.return_value = (
            "https://example.com/image.jpg"
        )
        page.notifier.personal_alert_phones.return_value = ["5511999999999"]
        page.notifier.format_alert.return_value = "mensagem"
        page.notifier.affiliate_link.return_value = "https://affiliate"
        product = {
            "titulo": "Produto",
            "loja": "Shopee",
            "link": "https://original",
        }

        page.send_to_selected_destination(
            product,
            "Casa & Ofertas",
            "house@g.us",
            send_personal_copy=True,
        )

        self.assertEqual(
            [
                call.args[2]
                for call in page.notifier.send_whatsapp_message.call_args_list
            ],
            ["house@g.us", "5511999999999"],
        )

    def test_erro_de_envio_nao_registra_como_enviado(self):
        page = self.page()
        page.database = Mock()
        page.notifier = Mock()
        page.notifier.whatsapp_configured.return_value = True
        page.notifier.evolution_configured.return_value = False
        page.notifier.has_affiliate_link.return_value = True
        page.notifier.verified_whatsapp_image.return_value = (
            "https://example.com/image.jpg"
        )
        page.notifier.format_alert.return_value = "mensagem"
        page.notifier.send_whatsapp_message.side_effect = RuntimeError("HTTP 500")

        result = page.send_to_selected_destination(
            {
                "titulo": "Produto",
                "loja": "Shopee",
                "link": "https://original",
            },
            "Casa & Ofertas",
            "house@g.us",
        )

        self.assertIn("HTTP 500", result)
        page.database.registrar_envio.assert_not_called()

    def test_nenhuma_falha_da_evolution_cria_registro_de_envio(self):
        failures = (
            "instância desconectada",
            "destino inválido",
            "arquivo vazio",
            "MIME incorreto",
            "HTTP 500: Unexpected field",
            "HTTP 500: erro interno",
        )
        for failure in failures:
            with self.subTest(failure=failure):
                page = self.page()
                page.database = Mock()
                page.notifier = Mock()
                page.notifier.whatsapp_configured.return_value = True
                page.notifier.evolution_configured.return_value = False
                page.notifier.has_affiliate_link.return_value = True
                page.notifier.verified_whatsapp_image.return_value = (
                    "https://example.com/image.jpg"
                )
                page.notifier.format_alert.return_value = "mensagem"
                page.notifier.send_whatsapp_message.side_effect = RuntimeError(
                    failure
                )

                result = page.send_to_selected_destination(
                    {
                        "titulo": "Produto preservado",
                        "loja": "Shopee",
                        "link": "https://original",
                    },
                    "Revisão PromoBot",
                    "120363408335461860@g.us",
                )

                self.assertIn(failure, result)
                page.database.registrar_envio.assert_not_called()

    @patch("src.ui.affiliate_links_page.messagebox")
    def test_categoria_ausente_nao_altera_destino_selecionado(self, messagebox):
        page = self.page()
        page.entry_mode = "Cadastro manual"
        page.manual_category = FakeVariable("Selecione a categoria")
        page.save_selected_link = Mock(return_value=None)
        page.select_manual_destination("review")

        with patch.dict(os.environ, {"WHATSAPP_REVIEW_GROUP": "review@g.us"}):
            page.save_and_notify()

        self.assertEqual(page.selected_destination.get(), "review")
        messagebox.showwarning.assert_not_called()

    @patch("src.ui.affiliate_links_page.messagebox")
    def test_falha_http_preserva_formulario_categoria_e_destino(self, messagebox):
        page = self.page()
        page.manual_title = FakeVariable("Produto preenchido")
        page.manual_category = FakeVariable("Casa e Enxoval")
        page.manual_details = Mock()
        page.manual_fallback_required = True
        page.shopee_manual_link = "https://example.com/produto"
        page.select_manual_destination("house")

        self.assertFalse(page.show_manual_destination_result(
            "Falha no envio para Casa & Ofertas: HTTP 500"
        ))

        self.assertEqual(page.manual_title.get(), "Produto preenchido")
        self.assertEqual(page.manual_category.get(), "Casa e Enxoval")
        self.assertEqual(page.selected_destination.get(), "house")
        self.assertTrue(page.manual_fallback_required)
        page.manual_details.grid_remove.assert_not_called()

    @patch("src.ui.affiliate_links_page.messagebox")
    def test_limpa_selecao_somente_apos_sucesso(self, messagebox):
        page = self.page()
        page.manual_details = Mock()
        page.manual_fallback_required = True
        page.shopee_manual_link = "https://example.com/produto"
        page.select_manual_destination("house")

        self.assertTrue(page.show_manual_destination_result(
            "Enviado por: WhatsApp — Casa & Ofertas."
        ))
        self.assertEqual(page.selected_destination.get(), "")
        self.assertFalse(page.manual_fallback_required)
        page.manual_details.grid_remove.assert_called_once()

        page.select_manual_destination("review")
        self.assertFalse(page.show_manual_destination_result("Falha"))
        self.assertEqual(page.selected_destination.get(), "review")


if __name__ == "__main__":
    unittest.main()
