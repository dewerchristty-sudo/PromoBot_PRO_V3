import unittest
from unittest.mock import Mock, patch

import requests

from src.stores.mercado_livre import MercadoLivre


class MercadoLivreRecoveryFallbacksTest(unittest.TestCase):

    def setUp(self):
        self.store = MercadoLivre.__new__(MercadoLivre)
        self.url = (
            "https://produto.mercadolivre.com.br/"
            "MLB-5476998610-produto-_JM"
        )

    def test_recupera_json_ld_antes_da_api(self):
        html = """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Produto estruturado",
          "image": ["https://http2.mlstatic.com/item.jpg"],
          "offers": {"price": 199.90}
        }
        </script>
        """
        with patch(
            "src.stores.mercado_livre.requests.get"
        ) as api_get:
            product = self.store.product_data_from_sources(html, self.url)

        self.assertEqual(product["titulo"], "Produto estruturado")
        self.assertEqual(product["preco"], "199,90")
        self.assertFalse(api_get.called)

    def test_recupera_open_graph_completo(self):
        html = """
        <meta property="og:title" content="Produto Open Graph">
        <meta property="og:image"
              content="https://http2.mlstatic.com/item-og.jpg">
        <meta property="product:price:amount" content="189,90">
        """
        product = self.store.product_data_from_sources(html, self.url)

        self.assertEqual(product["titulo"], "Produto Open Graph")
        self.assertEqual(product["preco"], "189,90")

    def test_recupera_estado_json_embutido(self):
        html = """
        <script type="application/json">
        {
          "item": {
            "id": "MLB5476998610",
            "title": "Produto no estado",
            "price": 179.9,
            "secure_thumbnail": "https://http2.mlstatic.com/state.jpg"
          }
        }
        </script>
        """
        product = self.store.product_data_from_sources(html, self.url)

        self.assertEqual(product["titulo"], "Produto no estado")
        self.assertEqual(product["preco"], "179,90")

    @patch("src.stores.mercado_livre.requests.get")
    def test_api_envia_headers_minimos_e_registra_403(self, api_get):
        response = Mock()
        response.status_code = 403
        response.headers = {"Content-Type": "application/json"}
        response.text = (
            '{"blocked_by":"PolicyAgent","code":"PA_UNAUTHORIZED"}'
        )
        response.raise_for_status.side_effect = requests.HTTPError(
            "403 Client Error"
        )
        api_get.return_value = response

        with self.assertLogs(
            "src.stores.mercado_livre", level="INFO"
        ) as captured:
            with self.assertRaisesRegex(ValueError, "403 Client Error"):
                self.store.product_data_from_api(self.url)

        headers = api_get.call_args.kwargs["headers"]
        self.assertIn("Mozilla/5.0", headers["User-Agent"])
        self.assertEqual(headers["Accept"], "application/json")
        self.assertEqual(headers["Accept-Language"], "pt-BR,pt;q=0.9")
        log = " ".join(captured.output)
        self.assertIn("status=403", log)
        self.assertIn("PolicyAgent", log)
        self.assertNotIn("Authorization", log)

    def test_nao_libera_produto_sem_imagem(self):
        product = {
            "titulo": "Produto",
            "preco": "99,90",
            "imagem": "",
        }
        with self.assertRaisesRegex(ValueError, "imagem"):
            self.store.validate_recovered_product(product, "TEST")


if __name__ == "__main__":
    unittest.main()
