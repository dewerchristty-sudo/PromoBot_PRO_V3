import unittest
from unittest.mock import Mock, patch

from src.ui.affiliate_links_page import AffiliateLinksPage


class MercadoLivreProductRecoveryTest(unittest.TestCase):

    def page(self):
        page = AffiliateLinksPage.__new__(AffiliateLinksPage)
        page.database = Mock()
        page.database.referencia_produto_link.return_value = "MLB4580504787"
        return page

    def product(self, **changes):
        value = {
            "loja": "Mercado Livre",
            "titulo": "SSD Kingston 1TB",
            "preco": "299,90",
            "preco_valor": 299.90,
            "link":
                "https://produto.mercadolivre.com.br/MLB-4580504787",
            "imagem": "https://http2.mlstatic.com/product.jpg",
        }
        value.update(changes)
        return value

    def test_localiza_por_url_ou_identificador_mlb(self):
        page = self.page()
        stored = {**self.product(), "id": 10}
        page.database.buscar_produto_por_link.return_value = stored
        result = page.ensure_mercado_livre_product_record(self.product())
        self.assertEqual(result, stored)
        page.database.salvar_produto.assert_not_called()

    def test_cria_com_payload_ja_carregado_sem_busca_manual(self):
        page = self.page()
        stored = {**self.product(), "id": 11}
        page.database.buscar_produto_por_link.side_effect = [None, stored]
        result = page.ensure_mercado_livre_product_record(self.product())
        self.assertEqual(result["id"], 11)
        saved = page.database.salvar_produto.call_args.args[0]
        self.assertEqual(saved["titulo"], "SSD Kingston 1TB")
        self.assertEqual(
            saved["link"],
            "https://produto.mercadolivre.com.br/MLB-4580504787",
        )

    @patch("src.ui.affiliate_links_page.MercadoLivre")
    def test_payload_incompleto_usa_pagina_do_produto(self, store_class):
        page = self.page()
        imported = self.product(
            titulo="Produto importado", breadcrumb="Informática > SSD"
        )
        store_class.return_value.product_from_url.return_value = imported
        stored = {**imported, "id": 12}
        page.database.buscar_produto_por_link.side_effect = [None, stored]
        result = page.ensure_mercado_livre_product_record(self.product(
            titulo="Cadastro manual", preco="", imagem=""
        ))
        self.assertEqual(result["id"], 12)
        store_class.return_value.product_from_url.assert_called_once()

    def test_falha_informa_identificador_ausente(self):
        page = self.page()
        page.database.referencia_produto_link.return_value = ""
        with self.assertRaisesRegex(ValueError, "identificador MLB"):
            page.ensure_mercado_livre_product_record(self.product())
        page.database.salvar_produto.assert_not_called()

    def test_falha_pos_criacao_e_auditavel(self):
        page = self.page()
        page.database.buscar_produto_por_link.return_value = None
        with self.assertLogs(
            "src.ui.affiliate_links_page", level="ERROR"
        ) as captured:
            with self.assertRaisesRegex(RuntimeError, "registro"):
                page.ensure_mercado_livre_product_record(self.product())
        log = "\n".join(captured.output)
        self.assertIn("identifier=MLB4580504787", log)
        self.assertIn("reason=RECORD_NOT_RECOVERED", log)

    def test_amazon_e_shopee_nao_entram_na_recuperacao_ml(self):
        source = __import__("pathlib").Path(
            "src/ui/affiliate_links_page.py"
        ).read_text(encoding="utf-8")
        call = (
            'if self.store_key(product) == "mercado livre":\n'
            "            try:\n"
            "                recovered = "
            "self.ensure_mercado_livre_product_record(product)"
        )
        self.assertIn(call, source)


if __name__ == "__main__":
    unittest.main()
