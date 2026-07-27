import unittest
from unittest.mock import Mock, patch

from src.stores.mercado_livre import MercadoLivre


class MercadoLivreProductFromUrlTest(unittest.TestCase):

    def test_extrai_produto_no_formato_do_pipeline(self):
        store = MercadoLivre.__new__(MercadoLivre)
        product = store.product_data_from_html(
            """
            <nav aria-label="breadcrumb">
              <a>Informática</a><a>Armazenamento</a><a>SSD</a>
            </nav>
            <h1 class="ui-pdp-title">SSD Kingston 1TB</h1>
            <div class="ui-pdp-price__second-line">
              <span class="andes-money-amount">
                <span class="andes-money-amount__fraction">1.159</span>
                <span class="andes-money-amount__cents">90</span>
              </span>
            </div>
            <meta property="og:image" content="https://http2.mlstatic.com/ssd.jpg">
            """,
            "https://produto.mercadolivre.com.br/MLB-4580504787",
        )
        self.assertEqual(product["loja"], "Mercado Livre")
        self.assertEqual(product["titulo"], "SSD Kingston 1TB")
        self.assertEqual(product["preco"], "1.159,90")
        self.assertEqual(
            product["link"],
            "https://produto.mercadolivre.com.br/MLB-4580504787",
        )
        self.assertEqual(
            product["imagem"], "https://http2.mlstatic.com/ssd.jpg"
        )
        self.assertEqual(
            product["breadcrumb"], "Informática > Armazenamento > SSD"
        )
        self.assertEqual(product["categoria_original"], "SSD")

    def test_rejeita_pagina_sem_dados_obrigatorios(self):
        store = MercadoLivre.__new__(MercadoLivre)
        with self.assertRaisesRegex(ValueError, "título e preço"):
            store.product_data_from_html(
                "<html><body>página vazia</body></html>",
                "https://produto.mercadolivre.com.br/MLB-4580504787",
            )

    @patch("src.stores.mercado_livre.requests.get")
    def test_fallback_api_publica_retorna_formato_do_pipeline(self, get):
        item_response = Mock()
        item_response.raise_for_status.return_value = None
        item_response.json.return_value = {
            "id": "MLB4580504787",
            "title": "Chinelo Kenner Masculino",
            "price": 159.9,
            "secure_thumbnail": "https://http2.mlstatic.com/chinelo.jpg",
            "category_id": "MLB123",
        }
        category_response = Mock()
        category_response.raise_for_status.return_value = None
        category_response.json.return_value = {
            "name": "Chinelos",
            "path_from_root": [
                {"name": "Moda"},
                {"name": "Calçados"},
            ],
        }
        get.side_effect = [item_response, category_response]
        store = MercadoLivre.__new__(MercadoLivre)
        product = store.product_data_from_api(
            "https://produto.mercadolivre.com.br/"
            "MLB-4580504787-chinelo-_JM"
        )
        self.assertEqual(product["titulo"], "Chinelo Kenner Masculino")
        self.assertEqual(product["preco"], "159,90")
        self.assertEqual(
            product["breadcrumb"], "Moda > Calçados > Chinelos"
        )
        self.assertEqual(product["categoria_original"], "Chinelos")
        self.assertEqual(get.call_count, 2)

    def test_extrai_identificador_mlb_da_url(self):
        self.assertEqual(
            MercadoLivre.product_id_from_url(
                "https://produto.mercadolivre.com.br/"
                "MLB-5339900262-produto-_JM"
            ),
            "MLB5339900262",
        )


if __name__ == "__main__":
    unittest.main()
