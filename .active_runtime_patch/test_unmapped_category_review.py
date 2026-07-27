import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.core.notifier import Notifier
from src.database.database import Database
from src.ui.affiliate_links_page import AffiliateLinksPage


class UnmappedCategoryReviewTest(unittest.TestCase):

    def test_categoria_original_e_persistida_e_usada_no_aprendizado(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "test.db")
            product = {
                "loja": "Mercado Livre",
                "titulo": "Produto sem palavra conhecida",
                "preco": "80,29",
                "link": "https://produto.mercadolivre.com.br/MLB-2757757904",
                "imagem": "https://http2.mlstatic.com/produto.webp",
                "categoria_original": "Calçados",
            }
            database.salvar_produto(product)
            saved = database.buscar_produto_por_link(product["link"])
            self.assertEqual(saved["categoria_original"], "Calçados")

            database.salvar_palavras_categoria(
                "casa_enxoval",
                "calçados",
            )
            self.assertEqual(
                Notifier(database).whatsapp_category(saved),
                "casa_enxoval",
            )
            database.fechar()

    @patch("src.ui.affiliate_links_page.messagebox")
    def test_categoria_desconhecida_vai_para_revisao_sem_bloquear(
        self,
        messagebox,
    ):
        page = AffiliateLinksPage.__new__(AffiliateLinksPage)
        page.database = Mock()
        page.notifier = Mock()
        page.notifier.send_review_alert.return_value = (
            "Oferta enviada para o grupo Revisao PromoBot."
        )
        page.trace_send_stage = Mock()
        page.load_pending = Mock()
        product = {
            "loja": "Mercado Livre",
            "titulo": "Chinelo masculino",
            "link": "https://produto.mercadolivre.com.br/MLB-2757757904",
            "categoria_original": "Calçados",
        }

        result = page.route_unmapped_category_to_review(
            product,
            "INSUFFICIENT",
        )

        self.assertTrue(result)
        page.database.registrar_pendencias_revisao.assert_called_once()
        args = page.database.registrar_pendencias_revisao.call_args.args
        self.assertEqual(args[1], "categoria")
        self.assertIn("Calçados", args[2])
        page.notifier.send_review_alert.assert_called_once()
        messagebox.showinfo.assert_called_once()
        messagebox.showerror.assert_not_called()

    @patch("src.ui.affiliate_links_page.messagebox")
    def test_falha_no_grupo_preserva_pendencia(self, messagebox):
        page = AffiliateLinksPage.__new__(AffiliateLinksPage)
        page.database = Mock()
        page.notifier = Mock()
        page.notifier.send_review_alert.return_value = (
            "Falha: grupo de revisao nao configurado."
        )
        page.trace_send_stage = Mock()
        page.load_pending = Mock()

        result = page.route_unmapped_category_to_review(
            {"titulo": "Produto", "categoria_original": "Calçados"},
        )

        self.assertFalse(result)
        page.database.registrar_pendencias_revisao.assert_called_once()
        messagebox.showerror.assert_called_once()


if __name__ == "__main__":
    unittest.main()
