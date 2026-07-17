import unittest

from src.core.store_manager import StoreManager
from src.stores.mercado_livre import MercadoLivre
from src.stores.shopee import Shopee


class StoresTest(unittest.TestCase):

    def test_lojas_registradas(self):

        nomes = [store.name for store in StoreManager().stores]

        self.assertIn("Mercado Livre", nomes)
        self.assertIn("Amazon", nomes)
        self.assertIn("Kabum", nomes)
        self.assertIn("Terabyte", nomes)
        self.assertIn("Pichau", nomes)
        self.assertIn("Magalu", nomes)
        self.assertIn("Casas Bahia", nomes)
        self.assertIn("Americanas", nomes)

    def test_lojas_estaveis_e_experimentais(self):

        self.assertIn("Mercado Livre", StoreManager.stable_store_names())
        self.assertIn("Amazon", StoreManager.stable_store_names())
        self.assertIn("Kabum", StoreManager.stable_store_names())
        self.assertIn("Shopee", StoreManager.stable_store_names())
        self.assertIn("Americanas", StoreManager.experimental_store_names())
        self.assertIn("Terabyte", StoreManager.experimental_store_names())

    def test_lojas_usam_navegador_oculto_por_padrao(self):

        store = MercadoLivre()

        self.assertTrue(store.browser_manager.headless)

    def test_shopee_extrai_titulo_e_preco_do_card_renderizado(self):

        store = Shopee()
        lines = store.text_lines(
            "Fone Bluetooth Sem Fio\nR$\n21,99\nR$\n65,80\n-67%"
        )

        self.assertEqual(
            store.extract_title(lines),
            "Fone Bluetooth Sem Fio"
        )
        self.assertEqual(store.extract_price(lines), "21,99")

    def test_sanitize_remove_resultados_invalidos(self):

        manager = StoreManager(enabled_stores=[])

        resultados = manager.sanitize_results([
            {
                "loja": "Teste",
                "titulo": "Produto valido",
                "preco": "R$ 10,00",
                "link": "https://example.com/produto?utm=1",
                "imagem": "",
            },
            {
                "loja": "Teste",
                "titulo": "",
                "preco": "R$ 20,00",
                "link": "https://example.com/invalido",
                "imagem": "",
            },
            {
                "loja": "Teste",
                "titulo": "Sem link",
                "preco": "R$ 30,00",
                "link": "",
                "imagem": "",
            },
        ])

        self.assertEqual(len(resultados), 1)
        self.assertEqual(resultados[0]["preco"], "10,00")
        self.assertEqual(resultados[0]["link"], "https://example.com/produto")


if __name__ == "__main__":
    unittest.main()
