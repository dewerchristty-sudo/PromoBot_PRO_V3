import os
import unittest
from unittest.mock import Mock, patch

from src.core.notifier import Notifier
from src.ui.affiliate_links_page import AffiliateLinksPage


class CategorySafetyTest(unittest.TestCase):

    def product(self, **changes):
        value = {
            "titulo": "SSD Kingston 1TB",
            "loja": "Mercado Livre",
            "preco": "299,90",
            "preco_valor": 299.90,
            "preco_antigo": "399,90",
            "maior_preco": 399.90,
            "link": "https://produto.mercadolivre.com.br/MLB-900000001",
            "link_afiliado_salvo": "https://meli.la/teste-seguro",
            "imagem": "https://example.com/ssd.jpg",
        }
        value.update(changes)
        return value

    @patch.dict(os.environ, {
        "WHATSAPP_GROUP_SMARTPHONES_TECNOLOGIA": "tech@g.us",
        "WHATSAPP_GROUPS": "", "WHATSAPP_PHONES": "",
    }, clear=False)
    def test_categoria_segura_tem_destino(self):
        diagnostic = Notifier().category_routing_diagnostic(self.product())
        self.assertEqual(
            diagnostic["canonical_category"], "smartphones_tecnologia"
        )
        self.assertEqual(diagnostic["reason"], "READY")
        self.assertTrue(diagnostic["destination_configured"])

    @patch.dict(os.environ, {
        "WHATSAPP_GROUP_SMARTPHONES_TECNOLOGIA": "",
        "WHATSAPP_GROUPS": "", "WHATSAPP_PHONES": "",
    }, clear=False)
    def test_categoria_detectada_sem_destino(self):
        diagnostic = Notifier().category_routing_diagnostic(self.product())
        self.assertEqual(
            diagnostic["reason"], "CATEGORY_WITHOUT_DESTINATION"
        )

    def test_categoria_ausente(self):
        diagnostic = Notifier().category_routing_diagnostic(
            self.product(titulo="Produto sem classificação xyz")
        )
        self.assertEqual(diagnostic["reason"], "CATEGORY_NOT_DETECTED")

    def test_categoria_manual_nao_mapeada(self):
        diagnostic = Notifier().category_routing_diagnostic(
            self.product(categoria_manual="categoria_desconhecida")
        )
        self.assertEqual(diagnostic["reason"], "CATEGORY_NOT_MAPPED")

    @patch.dict(os.environ, {
        "WHATSAPP_GROUP_SMARTPHONES_TECNOLOGIA": "",
        "WHATSAPP_GROUPS": "", "WHATSAPP_PHONES": "",
    }, clear=False)
    def test_mensagem_detalha_produto_categoria_e_acao(self):
        message = Notifier().category_block_message(self.product())
        self.assertIn("SSD Kingston 1TB", message)
        self.assertIn("Mercado Livre", message)
        self.assertIn("smartphones_tecnologia", message)
        self.assertIn("CATEGORY_WITHOUT_DESTINATION", message)
        self.assertIn("Central Categorias", message)

    @patch.dict(os.environ, {
        "WHATSAPP_GROUP_SMARTPHONES_TECNOLOGIA": "",
        "WHATSAPP_GROUPS": "", "WHATSAPP_PHONES": "",
        "MAX_OFFER_AGE_HOURS": "0", "MIN_DISCOUNT_PERCENT": "0",
        "MAX_NOTIFICATIONS_PER_HOUR": "0",
        "NOTIFICATION_START_HOUR": "0", "NOTIFICATION_END_HOUR": "24",
    }, clear=False)
    def test_confirmacao_manual_nao_libera_categoria(self):
        notifier = Notifier()
        notifier.send_whatsapp_message = Mock()
        result = notifier.send_manual_alerts([self.product()])
        self.assertIn("CATEGORY_WITHOUT_DESTINATION", result)
        notifier.send_whatsapp_message.assert_not_called()

    @patch.dict(os.environ, {
        "WHATSAPP_GROUP_SMARTPHONES_TECNOLOGIA": "tech@g.us",
        "WHATSAPP_GROUPS": "", "WHATSAPP_PHONES": "",
    }, clear=False)
    def test_nova_tentativa_pode_prosseguir_apos_configuracao_explicita(self):
        notifier = Notifier()
        ready, blocked = notifier.partition_whatsapp_routable([
            self.product(categoria_manual="smartphones_tecnologia")
        ])
        self.assertEqual(len(ready), 1)
        self.assertEqual(blocked, [])

    @patch.dict(os.environ, {
        "WHATSAPP_GROUP_SMARTPHONES_TECNOLOGIA": "",
        "WHATSAPP_GROUPS": "", "WHATSAPP_PHONES": "",
    }, clear=False)
    def test_preview_funciona_mesmo_bloqueado_e_nao_envia(self):
        page = AffiliateLinksPage.__new__(AffiliateLinksPage)
        page.notifier = Notifier()
        page.notifier.send_whatsapp_message = Mock()
        preview = page.build_message_preview(self.product())
        self.assertIn("De: R$ 399,90", preview)
        self.assertIn("Por: R$ 299,90", preview)
        self.assertIn("https://meli.la/teste-seguro", preview)
        self.assertIn("CATEGORY_WITHOUT_DESTINATION", preview)
        self.assertIn("nenhuma mensagem foi enviada", preview)
        page.notifier.send_whatsapp_message.assert_not_called()

    def test_shopee_amazon_e_ml_usam_mesmo_formatador_no_preview(self):
        page = AffiliateLinksPage.__new__(AffiliateLinksPage)
        page.notifier = Notifier()
        for store, link in (
            ("Shopee", "https://s.shopee.com.br/teste"),
            ("Amazon", "https://amzn.to/teste"),
            ("Mercado Livre", "https://meli.la/teste"),
        ):
            with self.subTest(store=store):
                product = self.product(
                    loja=store, link_afiliado_salvo=link,
                    categoria_manual="smartphones_tecnologia",
                )
                preview = page.build_message_preview(product)
                self.assertIn(store, preview)
                self.assertIn(link, preview)
                self.assertIn("PREVIEW", preview)

    def test_cadastro_manual_nao_persiste_categoria_oculta(self):
        source = __import__(
            "pathlib"
        ).Path("src/ui/affiliate_links_page.py").read_text(encoding="utf-8")
        self.assertNotIn("Aprovar categoria para envio", source)
        self.assertNotIn("category_approved_manually", source)
        self.assertIn("update_manual_category_visibility", source)


if __name__ == "__main__":
    unittest.main()
