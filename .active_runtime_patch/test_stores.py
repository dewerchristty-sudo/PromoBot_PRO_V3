import unittest
from unittest.mock import patch

from src.core.store_manager import StoreManager
from src.stores.amazon import Amazon
from src.stores.mercado_livre import MercadoLivre
from src.stores.shopee import Shopee


class StoresTest(unittest.TestCase):

    def test_mercado_livre_extrai_cartao_da_pagina_publica_de_ofertas(self):

        from bs4 import BeautifulSoup

        card = BeautifulSoup(
            """
            <div class="andes-card poly-card">
              <h3 class="poly-component__title-wrapper">
                <a class="poly-component__title"
                   href="https://www.mercadolivre.com.br/fritadeira/p/MLB123">
                  Fritadeira eletrica em oferta
                </a>
              </h3>
              <span class="andes-money-amount__fraction">299</span>
              <img src="https://http2.mlstatic.com/oferta.webp">
            </div>
            """,
            "lxml",
        ).select_one("div.poly-card")
        store = MercadoLivre.__new__(MercadoLivre)

        self.assertEqual(
            card.select_one(".poly-component__title").get_text(strip=True),
            "Fritadeira eletrica em oferta",
        )
        self.assertEqual(
            store.product_link(card),
            "https://www.mercadolivre.com.br/fritadeira/p/MLB123",
        )

    def test_amazon_extrai_produto_por_open_graph(self):

        store = Amazon.__new__(Amazon)
        product = store.product_data_from_html(
            """
            <meta property="og:title" content="Produto Amazon Manual">
            <meta property="og:image" content="https://images.example/item.jpg">
            <meta property="product:price:amount" content="149.90">
            """,
            "https://www.amazon.com.br/dp/B012345678",
        )

        self.assertEqual(product["titulo"], "Produto Amazon Manual")
        self.assertEqual(product["imagem"], "https://images.example/item.jpg")
        self.assertEqual(product["preco"], "149.90")

    def test_amazon_extrai_produto_por_json_ld(self):

        store = Amazon.__new__(Amazon)
        product = store.product_data_from_html(
            """
            <script type="application/ld+json">
            {"@type":"Product","name":"Produto Estruturado",
             "image":["https://images.example/structured.jpg"],
             "offers":{"price":"89.90"}}
            </script>
            """,
            "https://www.amazon.com.br/dp/B012345678",
        )

        self.assertEqual(product["titulo"], "Produto Estruturado")
        self.assertEqual(product["imagem"], "https://images.example/structured.jpg")
        self.assertEqual(product["preco"], "89.90")

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

        self.assertNotIn("Mercado Livre", StoreManager.stable_store_names())
        self.assertIn("Mercado Livre", StoreManager.experimental_store_names())
        self.assertIn("Shopee", StoreManager.stable_store_names())
        self.assertIn("Amazon", StoreManager.stable_store_names())
        self.assertIn("Kabum", StoreManager.stable_store_names())
        self.assertNotIn("Shopee", StoreManager.experimental_store_names())
        self.assertIn("Americanas", StoreManager.experimental_store_names())
        self.assertIn("Terabyte", StoreManager.experimental_store_names())

    def test_lojas_marcadas_por_padrao(self):

        self.assertEqual(
            StoreManager.default_store_names(),
            ["Mercado Livre", "Shopee", "Amazon"]
        )

    def test_so_mercado_livre_pode_usar_perfil_visivel(self):

        with patch.dict("os.environ", {
            "MERCADO_LIVRE_PERSISTENT_PROFILE_ENABLED": "True",
            "MERCADO_LIVRE_HEADLESS": "False",
        }):
            mercado_livre = MercadoLivre()
            amazon = Amazon()
            shopee = Shopee()

        self.assertFalse(mercado_livre.browser_manager.headless)
        self.assertTrue(amazon.browser_manager.headless)
        self.assertTrue(shopee.browser_manager.headless)

    def test_mercado_livre_so_usa_ofertas_em_busca_generica(self):

        self.assertTrue(
            MercadoLivre.is_generic_offers_query("ofertas do dia")
        )
        self.assertTrue(
            MercadoLivre.is_generic_offers_query("PROMOÇÕES")
        )
        self.assertFalse(
            MercadoLivre.is_generic_offers_query("ssd 1tb")
        )
        self.assertFalse(
            MercadoLivre.is_generic_offers_query("notebook em promoção")
        )

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

    def test_filtra_capacidade_solicitada(self):

        produtos = [
            {"titulo": "SSD NVMe 1TB"},
            {"titulo": "SSD SATA 1000 GB"},
            {"titulo": "SSD 1024GB para notebook"},
            {"titulo": "SSD para servidor 128 Giga"},
            {"titulo": "SSD Kingston 960GB"},
            {"titulo": "SSD M.2 sem capacidade informada"},
        ]

        filtrados = StoreManager.filter_by_requested_capacity("ssd 1tb", produtos)

        self.assertEqual(
            [produto["titulo"] for produto in filtrados],
            [
                "SSD NVMe 1TB",
                "SSD SATA 1000 GB",
                "SSD 1024GB para notebook",
            ]
        )

    def test_busca_sem_capacidade_nao_filtra_resultados(self):

        produtos = [{"titulo": "Notebook sem capacidade informada"}]

        self.assertEqual(
            StoreManager.filter_by_requested_capacity("notebook gamer", produtos),
            produtos
        )

    def test_busca_por_ssd_rejeita_hd_externo(self):

        produtos = [
            {"titulo": "SSD Kingston NVMe 1TB"},
            {"titulo": "Solid State Drive SATA 1TB"},
            {"titulo": "Disco Rigido Externo HD 1TB Expansion"},
        ]

        filtrados = StoreManager.filter_by_requested_product_type(
            "ssd 1tb",
            produtos
        )

        self.assertEqual(
            [produto["titulo"] for produto in filtrados],
            ["SSD Kingston NVMe 1TB", "Solid State Drive SATA 1TB"]
        )

    def test_busca_por_codigo_rejeita_outros_modelos(self):

        produtos = [
            {
                "titulo": (
                    "Memoria Kingston Fury Impact DDR4 16GB 3200MHz "
                    "KF432S20IB/16"
                )
            },
            {
                "titulo": "Memoria RAM DDR3 16GB ECC SK Hynix HMT42GR7BFR4C"
            },
        ]

        filtrados = StoreManager.filter_by_requested_model_codes(
            "Kingston Fury Impact KF432S20IB/16",
            produtos
        )

        self.assertEqual(len(filtrados), 1)
        self.assertIn("KF432S20IB/16", filtrados[0]["titulo"])

    def test_codigo_aceita_separadores_diferentes(self):

        produtos = [{"titulo": "Memoria Kingston KF432S20IB-16 DDR4"}]

        filtrados = StoreManager.filter_by_requested_model_codes(
            "KF432S20IB/16",
            produtos
        )

        self.assertEqual(produtos, filtrados)

    def test_relevancia_exige_produto_e_marca_pesquisados(self):

        produtos = [
            {
                "titulo": "Notebook Acer Aspire 3 8GB SSD",
                "preco": "2.499,00",
            },
            {
                "titulo": "Notebook Lenovo IdeaPad 8GB SSD",
                "preco": "2.299,00",
            },
            {
                "titulo": "Carregador para Notebook Acer Aspire",
                "preco": "99,00",
            },
        ]

        filtrados = StoreManager.filter_by_query_relevance(
            "notebook acer",
            produtos,
        )

        self.assertEqual(
            [produto["titulo"] for produto in filtrados],
            ["Notebook Acer Aspire 3 8GB SSD"],
        )

    def test_busca_generica_de_promocao_nao_remove_resultados(self):

        produtos = [{"titulo": "Umidificador ultrassonico", "preco": "15,00"}]

        self.assertEqual(
            StoreManager.filter_by_query_relevance("ofertas do dia", produtos),
            produtos,
        )

    def test_relevancia_funciona_para_produtos_de_qualquer_categoria(self):

        produtos = [
            {"titulo": "Umidificador de ar 3 litros", "preco": "15,00"},
            {"titulo": "Ventilador de mesa", "preco": "99,00"},
        ]

        filtrados = StoreManager.filter_by_query_relevance(
            "umidificador",
            produtos,
        )

        self.assertEqual(len(filtrados), 1)
        self.assertIn("Umidificador", filtrados[0]["titulo"])
