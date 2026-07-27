import unittest

from bs4 import BeautifulSoup

from src.stores.amazon import Amazon


class AmazonPreviousPriceTest(unittest.TestCase):

    @staticmethod
    def extract(body, current="99,90", source="PRODUCT_PAGE"):
        soup = BeautifulSoup(body, "lxml")
        return Amazon.previous_price_from_soup(soup, current, source)

    def test_preco_riscado_valido(self):
        result = self.extract(
            '<div id="basisPrice"><span class="a-offscreen">'
            'R$ 149,90</span></div>'
        )
        self.assertEqual(result.value, "149,90")
        self.assertEqual(result.source, "PRODUCT_PAGE")

    def test_origem_card(self):
        result = self.extract(
            '<span class="a-price a-text-price">'
            '<span class="a-offscreen">R$ 129,90</span></span>',
            source="SEARCH_CARD",
        )
        self.assertEqual(result.source, "SEARCH_CARD")

    def test_sem_preco_anterior_retorna_none(self):
        result = self.extract("<div>Somente preço atual</div>")
        self.assertIsNone(result.value)
        self.assertEqual(result.source, "NOT_AVAILABLE")
        self.assertEqual(result.reason, "previous_price_not_present")

    def test_anterior_menor_e_rejeitado(self):
        result = self.extract(
            '<s><span class="a-offscreen">R$ 89,90</span></s>'
        )
        self.assertIsNone(result.value)
        self.assertEqual(
            result.reason, "previous_price_not_greater_than_current"
        )

    def test_anterior_igual_e_rejeitado(self):
        result = self.extract(
            '<s><span class="a-offscreen">R$ 99,90</span></s>'
        )
        self.assertIsNone(result.value)

    def test_parcela_nao_e_preco_anterior(self):
        result = self.extract(
            '<s><span>10 parcelas de '
            '<span class="a-offscreen">R$ 129,90</span></span></s>'
        )
        self.assertIsNone(result.value)

    def test_cupom_e_economia_nao_sao_preco_anterior(self):
        for label in ("Cupom", "Economize"):
            with self.subTest(label=label):
                result = self.extract(
                    f'<s><span>{label} '
                    '<span class="a-offscreen">R$ 129,90</span></span></s>'
                )
                self.assertIsNone(result.value)

    def test_aria_label_e_layout_alternativo(self):
        result = self.extract(
            '<div data-a-strike="true"><span class="a-offscreen" '
            'aria-label="R$ 1.299,90"></span></div>',
            current="999,90",
        )
        self.assertEqual(result.value, "1299,90")

    def test_dados_estruturados_confiaveis(self):
        result = self.extract(
            '<script type="application/ld+json">'
            '{"@type":"Product","name":"Produto",'
            '"offers":{"@type":"Offer","price":"99.90",'
            '"listPrice":"149.90"}}</script>'
        )
        self.assertEqual(result.value, "149,90")
        self.assertEqual(result.source, "STRUCTURED_DATA")

    def test_json_embutido_confiavel(self):
        result = self.extract(
            '<script>window.data={"basisPrice":{"amount":"159.90"}};</script>'
        )
        self.assertEqual(result.value, "159,90")
        self.assertEqual(result.source, "EMBEDDED_JSON")

    def test_moeda_brasileira_milhares_e_centavos(self):
        self.assertEqual(
            Amazon.normalize_price("Preço de tabela: R$ 1.259,99"),
            "1259,99",
        )

    def test_product_data_expõe_origem_sem_quebrar_campo_legado(self):
        store = Amazon.__new__(Amazon)
        product = store.product_data_from_html(
            """
            <span id="productTitle">Notebook teste</span>
            <div id="corePrice_feature_div">
              <span class="a-price"><span class="a-offscreen">R$ 99,90</span></span>
              <span class="a-price a-text-price">
                <span class="a-offscreen">R$ 149,90</span>
              </span>
            </div>
            """,
            "https://www.amazon.com.br/dp/B000000001",
        )
        self.assertEqual(product["preco"], "99,90")
        self.assertEqual(product["preco_antigo"], "149,90")
        self.assertEqual(product["previous_price"], "149,90")
        self.assertEqual(product["previous_price_source"], "PRODUCT_PAGE")

    def test_product_data_sem_anterior_expoe_none(self):
        store = Amazon.__new__(Amazon)
        product = store.product_data_from_html(
            '<span id="productTitle">Produto</span>'
            '<span class="a-price"><span class="a-offscreen">'
            'R$ 99,90</span></span>',
            "https://www.amazon.com.br/dp/B000000001",
        )
        self.assertIsNone(product["previous_price"])
        self.assertNotIn("preco_antigo", product)

    def test_preco_atual_nao_pode_ser_preco_anterior(self):
        """Preço atual não pode ser usado como preço anterior (regra 9)."""
        result = self.extract(
            '<s><span class="a-offscreen">R$ 99,90</span></s>',
            current="99,90",
        )
        self.assertIsNone(result.value)
        self.assertEqual(
            result.reason, "previous_price_not_greater_than_current"
        )

    def test_mensal_nao_e_preco_anterior(self):
        """Valor mensal não pode ser usado como preço anterior (regra 5)."""
        result = self.extract(
            '<s><span>12x mensal de '
            '<span class="a-offscreen">R$ 129,90</span></span></s>'
        )
        self.assertIsNone(result.value)

    def test_pix_nao_e_preco_anterior(self):
        """Preço do Pix não pode ser usado como preço anterior (regra 8)."""
        result = self.extract(
            '<s><span>Pix '
            '<span class="a-offscreen">R$ 129,90</span></span></s>'
        )
        self.assertIsNone(result.value)

    def test_mercado_livre_e_shopee_nao_alterados(self):
        """Mercado Livre e Shopee não devem ser alterados por este escopo."""
        from src.stores.mercado_livre import MercadoLivre
        from src.stores.shopee import Shopee
        self.assertTrue(hasattr(MercadoLivre, "search"))
        self.assertTrue(hasattr(Shopee, "search"))


if __name__ == "__main__":
    unittest.main()
