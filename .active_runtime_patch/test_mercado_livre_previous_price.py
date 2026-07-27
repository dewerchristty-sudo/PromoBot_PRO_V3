import tempfile
import unittest
from pathlib import Path

from src.core.notifier import Notifier
from src.database.database import Database
from src.stores.mercado_livre import MercadoLivre


class MercadoLivrePreviousPriceTest(unittest.TestCase):

    def setUp(self):
        self.store = MercadoLivre.__new__(MercadoLivre)
        self.url = (
            "https://produto.mercadolivre.com.br/"
            "MLB-2757757904-chinelo-_JM"
        )

    def test_extrai_preco_anterior_riscado(self):
        product = self.store.product_data_from_html(
            """
            <h1 class="ui-pdp-title">Chinelo Kenner</h1>
            <div class="ui-pdp-price__original-value">
              <span class="andes-money-amount andes-money-amount--previous">
                <span class="andes-money-amount__fraction">129</span>
                <span class="andes-money-amount__cents">90</span>
              </span>
            </div>
            <div class="ui-pdp-price__second-line">
              <span class="andes-money-amount">
                <span class="andes-money-amount__fraction">80</span>
                <span class="andes-money-amount__cents">29</span>
              </span>
            </div>
            <meta property="og:image"
                  content="https://http2.mlstatic.com/chinelo.webp">
            """,
            self.url,
        )
        self.assertEqual(product["preco"], "80,29")
        self.assertEqual(product["preco_antigo"], "129,90")

    def test_nao_inventa_preco_anterior_quando_ausente(self):
        product = self.store.build_product(
            self.url,
            "Chinelo Kenner",
            80.29,
            "https://http2.mlstatic.com/chinelo.webp",
        )
        self.assertNotIn("preco_antigo", product)

    def test_descarta_preco_anterior_menor_que_atual(self):
        product = self.store.build_product(
            self.url,
            "Chinelo Kenner",
            80.29,
            "https://http2.mlstatic.com/chinelo.webp",
            old_price=70,
        )
        self.assertNotIn("preco_antigo", product)

    def test_banco_persiste_e_mensagem_exibe_preco_anterior(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "test.db")
            database.salvar_produto({
                "loja": "Mercado Livre",
                "titulo": "Chinelo Kenner",
                "preco": "80,29",
                "preco_antigo": "129,90",
                "link": self.url,
                "imagem": "https://http2.mlstatic.com/chinelo.webp",
            })
            saved = database.buscar_produto_por_link(self.url)
            self.assertEqual(saved["preco_antigo"], 129.9)
            message = Notifier(database).format_alert(saved)
            self.assertIn("Preço anterior:", message)
            self.assertIn("De: R$ 129,90", message)
            database.fechar()


if __name__ == "__main__":
    unittest.main()
