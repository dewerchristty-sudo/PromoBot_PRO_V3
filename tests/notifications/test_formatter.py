import unittest
from enum import Enum

from src.notifications import (
    MessageStyle,
    NotificationOffer,
    OfferNotificationFormatter,
    format_brl_currency,
    format_discount_percent,
)


class Rating(str, Enum):
    EXCELLENT = "Excelente"


class OfferNotificationFormatterTest(unittest.TestCase):

    def setUp(self):
        self.offer = NotificationOffer(
            title="Notebook Pro",
            store="Loja Exemplo",
            current_price=1299.90,
            previous_price=1599.90,
            savings=300,
            discount_percent=18.751,
            classification="Boa oferta",
            product_link="https://example.com/produto",
            image_link="https://example.com/imagem.jpg",
        )
        self.formatter = OfferNotificationFormatter()

    def test_cria_notificacao_tipificada(self):
        notification = self.formatter.create(self.offer)

        self.assertEqual(notification.style, MessageStyle.COMPLETE)
        self.assertIn("Notebook Pro", notification.message)
        self.assertEqual(notification.product_link, self.offer.product_link)
        self.assertEqual(notification.image_link, self.offer.image_link)

    def test_mensagem_curta_omite_detalhes(self):
        message = self.formatter.short(self.offer).message

        self.assertIn("Notebook Pro", message)
        self.assertIn("Preço: R$ 1.299,90", message)
        self.assertIn("18,8% de desconto", message)
        self.assertIn("Classificação: Boa oferta", message)
        self.assertIn(self.offer.product_link, message)
        self.assertNotIn("Loja:", message)
        self.assertNotIn("Preço anterior:", message)
        self.assertNotIn("Economia:", message)
        self.assertNotIn("Imagem:", message)

    def test_mensagem_completa_contem_todos_os_dados(self):
        message = self.formatter.complete(self.offer).message

        self.assertIn("Loja: Loja Exemplo", message)
        self.assertIn("Preço anterior: R$ 1.599,90", message)
        self.assertIn("Economia: R$ 300,00", message)
        self.assertIn("Imagem: https://example.com/imagem.jpg", message)

    def test_formata_moeda_brasileira(self):
        cases = {
            1299.9: "R$ 1.299,90",
            "25,990.00": "R$ 25.990,00",
            "1.234,56": "R$ 1.234,56",
            0: "R$ 0,00",
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(format_brl_currency(value), expected)

    def test_formata_percentual(self):
        self.assertEqual(format_discount_percent(25), "25% de desconto")
        self.assertEqual(format_discount_percent("12,54"), "12,5% de desconto")

    def test_ausencia_de_preco_anterior_omite_campos_derivados(self):
        message = self.formatter.complete(NotificationOffer(
            title="Produto",
            current_price=100,
        )).message

        self.assertNotIn("Preço anterior:", message)
        self.assertNotIn("Economia:", message)
        self.assertNotIn("desconto", message)

    def test_calcula_economia_e_desconto_quando_precos_estao_disponiveis(self):
        message = self.formatter.complete(NotificationOffer(
            title="Produto",
            current_price=75,
            previous_price=100,
        )).message

        self.assertIn("Economia: R$ 25,00", message)
        self.assertIn("25% de desconto", message)

    def test_ausencia_de_imagem_nao_exibe_rotulo_vazio(self):
        message = self.formatter.complete(NotificationOffer(
            title="Produto",
            image_link="",
        )).message

        self.assertNotIn("Imagem:", message)

    def test_ausencia_de_link_nao_exibe_rotulo_vazio(self):
        notification = self.formatter.short(NotificationOffer(
            title="Produto",
            product_link=None,
        ))

        self.assertEqual(notification.message, "Produto")
        self.assertEqual(notification.product_link, "")

    def test_campos_invalidos_sao_omitidos_sem_excecao(self):
        message = self.formatter.complete({
            "titulo": "Produto",
            "preco": "inválido",
            "preco_antigo": -10,
            "desconto": float("nan"),
            "link": "javascript:alert(1)",
            "imagem": object(),
        }).message

        self.assertEqual(message, "Produto")
        self.assertNotIn("Preço:", message)
        self.assertNotIn("javascript:", message)

    def test_titulo_vazio_nao_exibe_linha_vazia(self):
        message = self.formatter.short(NotificationOffer(
            title=" \x00 ",
            store="Loja",
            current_price=10,
        )).message

        self.assertEqual(message, "Preço: R$ 10,00")
        self.assertNotIn("\n\n", message)

    def test_textos_personalizados(self):
        formatter = OfferNotificationFormatter(
            opening_text="🔥 Oferta selecionada",
            closing_text="Aproveite enquanto durar!",
        )
        message = formatter.short(self.offer).message

        self.assertTrue(message.startswith("🔥 Oferta selecionada\n"))
        self.assertTrue(message.endswith("\nAproveite enquanto durar!"))

        overridden = formatter.short(
            self.offer,
            opening_text="Nova abertura",
            closing_text="Novo fim",
        ).message
        self.assertTrue(overridden.startswith("Nova abertura\n"))
        self.assertTrue(overridden.endswith("\nNovo fim"))

    def test_classificacao_enum_e_preservada(self):
        message = self.formatter.short(NotificationOffer(
            title="Produto",
            classification=Rating.EXCELLENT,
        )).message

        self.assertIn("Classificação: Excelente", message)

    def test_caracteres_especiais_sao_preservados_com_seguranca(self):
        message = self.formatter.short(NotificationOffer(
            title="Smart TV 55” — 4K & Wi‑Fi 🔥\x00",
            store="Loja",
        )).message

        self.assertEqual(message, "Smart TV 55” — 4K & Wi‑Fi 🔥")
        self.assertNotIn("\x00", message)

    def test_nenhum_campo_vazio_aparece_na_mensagem(self):
        message = self.formatter.complete(NotificationOffer(
            title="Produto",
            store="",
            current_price=None,
            classification="",
            product_link="",
            image_link="",
        )).message

        self.assertEqual(message, "Produto")
        for empty_field in (
            "Loja:",
            "Preço:",
            "Classificação:",
            "Imagem:",
        ):
            self.assertNotIn(empty_field, message)

    def test_mapping_em_portugues_sem_dependencia_de_loja_ou_interface(self):
        notification = self.formatter.complete({
            "titulo": "Cafeteira",
            "loja": "Qualquer Loja",
            "preco_valor": 250,
            "preco_antigo": 300,
            "classificacao": "Excelente",
            "link_afiliado": "https://example.com/a",
            "imagem": "https://example.com/a.jpg",
        })

        self.assertIn("Cafeteira", notification.message)
        self.assertIn("Loja: Qualquer Loja", notification.message)
        self.assertNotIn("WhatsApp", notification.message)

    def test_modelo_invalido_usa_completo_sem_quebrar(self):
        notification = self.formatter.create(self.offer, style="desconhecido")

        self.assertEqual(notification.style, MessageStyle.COMPLETE)
        self.assertIn("Loja:", notification.message)

    def test_objeto_invalido_retorna_notificacao_vazia(self):
        notification = self.formatter.create(object())

        self.assertEqual(notification.message, "")
        self.assertEqual(notification.product_link, "")
        self.assertEqual(notification.image_link, "")


if __name__ == "__main__":
    unittest.main()
