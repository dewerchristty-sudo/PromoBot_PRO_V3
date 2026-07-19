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
        self.assertIn("Shopee", StoreManager.stable_store_names())
        self.assertIn("Amazon", StoreManager.experimental_store_names())
        self.assertIn("Kabum", StoreManager.experimental_store_names())
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

    def test_shopee_detecta_pagina_verify(self):

        store = Shopee()

        class FakePage:
            url = "https://shopee.com.br/verify/traffic/error?home_url=https://shopee.com.br"
            def content(self):
                return '<html>redirect_to_error_page</html>'

        self.assertTrue(store.is_verify_page(FakePage()))

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

    def test_search_all_sanitizes_and_continues_on_store_error(self):

        class FakeStore:
            def __init__(self, name, results=None, raise_error=False):
                self.name = name
                self._results = results or []
                self._raise_error = raise_error

            def search(self, product):
                if self._raise_error:
                    raise RuntimeError("fail")
                return self._results

        manager = StoreManager(enabled_stores=[])
        manager.stores = [
            FakeStore(
                "GoodStore",
                [
                    {
                        "loja": "GoodStore",
                        "titulo": "Produto valido",
                        "preco": "R$ 15,00",
                        "link": "https://example.com/produto",
                        "imagem": "",
                    },
                    {
                        "loja": "GoodStore",
                        "titulo": "Produto duplicado",
                        "preco": "R$ 20,00",
                        "link": "https://example.com/produto",
                        "imagem": "",
                    },
                ],
            ),
            FakeStore("BadStore", raise_error=True),
        ]

        logs: list[str] = []
        manager.progress_callback = lambda message: logs.append(message)

        resultados = manager.search_all("teste")

        self.assertEqual(len(resultados), 1)
        self.assertEqual(resultados[0]["titulo"], "Produto valido")
        self.assertTrue(any("[ERRO] BadStore" in linha for linha in logs))

    def test_enabled_stores_filters_registered_stores(self):

        manager = StoreManager(enabled_stores=["Mercado Livre", "Shopee"])

        nomes = [store.name for store in manager.stores]

        self.assertEqual(set(nomes), {"Mercado Livre", "Shopee"})
        self.assertNotIn("Amazon", nomes)
        self.assertNotIn("Kabum", nomes)

    def test_empty_enabled_stores_selects_no_store(self):

        manager = StoreManager(enabled_stores=[])

        self.assertEqual(manager.stores, [])

    def test_sanitize_deduplicates_links_after_removing_tracking(self):

        manager = StoreManager(enabled_stores=[])
        resultados = manager.sanitize_results([
            {
                "loja": "Teste",
                "titulo": "Produto com campanha A",
                "preco": "R$ 10,00",
                "link": "https://example.com/produto?campaign=a",
                "imagem": "",
            },
            {
                "loja": "Teste",
                "titulo": "Produto com campanha B",
                "preco": "R$ 10,00",
                "link": "https://example.com/produto?campaign=b",
                "imagem": "",
            },
        ])

        self.assertEqual(len(resultados), 1)
        self.assertEqual(resultados[0]["link"], "https://example.com/produto")

    def test_store_name_lists_return_copies(self):

        stable_names = StoreManager.stable_store_names()
        experimental_names = StoreManager.experimental_store_names()

        stable_names.append("Dummy")
        experimental_names.append("Dummy")

        self.assertNotIn("Dummy", StoreManager.STABLE_STORES)
        self.assertNotIn("Dummy", StoreManager.EXPERIMENTAL_STORES)
