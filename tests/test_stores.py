import unittest

from src.core.store_manager import StoreManager


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
        self.assertIn("Americanas", StoreManager.experimental_store_names())
        self.assertIn("Terabyte", StoreManager.experimental_store_names())
        self.assertIn("Shopee", StoreManager.experimental_store_names())

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
