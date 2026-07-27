import unittest
from unittest.mock import Mock, patch

from src.core.store_manager import StoreManager
from src.stores.amazon import Amazon
from src.stores.mercado_livre import MercadoLivre
from src.stores.shopee import Shopee


class StoresTest(unittest.TestCase):

    def setUp(self):
        self.offer_shadow_disabled = patch.dict(
            "os.environ",
            {"OFFER_SHADOW_PIPELINE_ENABLED": "False"},
        )
        self.offer_shadow_disabled.start()

    def tearDown(self):
        self.offer_shadow_disabled.stop()

    @patch.dict(
        "os.environ",
        {"OFFER_SHADOW_PIPELINE_ENABLED": "True"},
    )
    def test_store_manager_observa_sem_alterar_resultados(self):

        pipeline = Mock()
        pipeline.process_batch.return_value.metrics = type(
            "Metrics",
            (),
            {
                "received_count": 1,
                "queued_count": 1,
                "selected_shadow_count": 0,
            },
        )()
        manager = StoreManager(enabled_stores=[], offer_pipeline=pipeline)
        products = [{"titulo": "Produto", "loja": "Amazon"}]

        returned = manager.observe_offer_shadow(products)

        pipeline.process_batch.assert_called_once_with(products)
        self.assertIs(returned, pipeline.process_batch.return_value)
        self.assertEqual(products, [{"titulo": "Produto", "loja": "Amazon"}])

    @patch.dict(
        "os.environ",
        {"OFFER_SHADOW_PIPELINE_ENABLED": "True"},
    )
    def test_falha_do_pipeline_preserva_coleta_antiga(self):

        pipeline = Mock()
        pipeline.process_batch.side_effect = RuntimeError("falha sombra")
        manager = StoreManager(enabled_stores=[], offer_pipeline=pipeline)
        products = [{"titulo": "Produto", "loja": "Amazon"}]

        self.assertIsNone(manager.observe_offer_shadow(products))
        self.assertEqual(products, [{"titulo": "Produto", "loja": "Amazon"}])

    @patch.dict(
        "os.environ",
        {"OFFER_SHADOW_PIPELINE_ENABLED": "False"},
    )
    def test_flag_desativa_pipeline_sem_consultas_adicionais(self):

        pipeline = Mock()
        manager = StoreManager(enabled_stores=[], offer_pipeline=pipeline)

        self.assertIsNone(manager.observe_offer_shadow([]))
        pipeline.process_batch.assert_not_called()

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

    def test_mercado_livre_converte_link_de_recomendacao_com_wid(self):

        from bs4 import BeautifulSoup

        card = BeautifulSoup(
            """
            <div>
              <a href="https://www.mercadolivre.com.br/navigation/recos?item_id=abc&amp;wid=MLB4580504787&amp;sid=recos">
                Produto recomendado
              </a>
            </div>
            """,
            "lxml",
        ).div
        store = MercadoLivre.__new__(MercadoLivre)

        self.assertEqual(
            store.product_link(card),
            "https://produto.mercadolivre.com.br/MLB-4580504787",
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
        self.assertEqual(product["preco"], "149,90")

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
        self.assertEqual(product["preco"], "89,90")

    def test_amazon_extrai_preco_anterior_riscado(self):

        store = Amazon.__new__(Amazon)
        product = store.product_data_from_html(
            """
            <span id="productTitle">Produto Amazon em oferta</span>
            <div id="corePrice_feature_div">
              <span class="a-price">
                <span class="a-offscreen">R$ 79,90</span>
              </span>
            </div>
            <div id="basisPrice">
              <span class="a-price a-text-price">
                <span class="a-offscreen">R$ 129,90</span>
              </span>
            </div>
            <img id="landingImage" src="https://example.com/oferta.jpg">
            """,
            "https://www.amazon.com.br/dp/B000TESTE",
        )

        self.assertEqual(product["preco"], "79,90")
        self.assertEqual(product["preco_antigo"], "129,90")

    def test_amazon_normaliza_preco_decimal_dos_metadados(self):

        self.assertEqual(Amazon.normalize_price("39.90"), "39,90")
        self.assertEqual(Amazon.normalize_price("R$ 1.299,90"), "1299,90")

    def test_lojas_registradas(self):

        nomes = [store.name for store in StoreManager().stores]

        self.assertIn("Mercado Livre", nomes)
        self.assertIn("Amazon", nomes)
        self.assertIn("Shopee", nomes)
        self.assertEqual(
            nomes, ["Mercado Livre", "Amazon", "Shopee"]
        )

    def test_lojas_estaveis_e_experimentais(self):

        self.assertEqual(
            StoreManager.stable_store_names(),
            ["Mercado Livre", "Amazon", "Shopee"],
        )
        self.assertEqual(StoreManager.experimental_store_names(), [])

    def test_lojas_marcadas_por_padrao(self):

        self.assertEqual(
            StoreManager.default_store_names(),
            ["Mercado Livre", "Amazon", "Shopee"]
        )

    def test_mercado_livre_persistente_inicia_visivel_por_seguranca(self):

        store = MercadoLivre()

        self.assertFalse(store.browser_manager.headless)

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

    def test_shopee_normaliza_preco_decimal_dos_metadados(self):

        self.assertEqual(Shopee.normalize_price("31.97"), "31,97")
        self.assertEqual(Shopee.normalize_price("R$ 1.299,90"), "1299,90")
        self.assertEqual(Shopee.normalize_price("3197000"), "31,97")

    def test_shopee_extrai_preco_atual_e_anterior_do_json(self):

        from bs4 import BeautifulSoup

        soup = BeautifulSoup(
            """
            <script>
              {"price":3197000,"price_before_discount":5390000}
            </script>
            """,
            "lxml",
        )

        self.assertEqual(
            Shopee.prices_from_page(soup),
            ("31,97", "53,90"),
        )

    def test_shopee_extrai_preco_anterior_de_json_escapado(self):

        from bs4 import BeautifulSoup

        soup = BeautifulSoup(
            r'<script>{"data":"{\"price_before_discount\":7990000}"}</script>',
            "lxml",
        )

        self.assertEqual(Shopee.prices_from_page(soup)[1], "79,90")

    def test_shopee_extrai_preco_anterior_riscado_da_pagina(self):

        class FakePage:
            @staticmethod
            def evaluate(_script):
                return ["R$53,90", "R$ 29,00"]

        self.assertEqual(
            Shopee.old_price_from_visible_page(FakePage(), "31,97"),
            "53,90",
        )

    def test_shopee_detecta_pagina_verify(self):

        store = Shopee()

        class FakePage:
            url = "https://shopee.com.br/verify/traffic/error?home_url=https://shopee.com.br"
            def content(self):
                return '<html>redirect_to_error_page</html>'

        self.assertTrue(store.is_verify_page(FakePage()))

    def test_shopee_filtra_anuncio_patrocinado(self):

        self.assertTrue(
            Shopee._is_invalid_ad("Fone Bluetooth", ["Patrocinado", "Fone Bluetooth"])
        )
        self.assertTrue(
            Shopee._is_invalid_ad("Mouse Gamer", ["Anúncio", "Mouse Gamer"])
        )
        self.assertFalse(
            Shopee._is_invalid_ad("Fone Bluetooth Sem Fio", ["Fone Bluetooth Sem Fio", "R$ 21,99"])
        )

    def test_shopee_extrai_preco_anterior_das_linhas_do_card(self):

        self.assertEqual(
            Shopee._extract_old_price_from_lines(
                ["Fone Bluetooth", "R$ 21,99", "R$ 65,80", "-67%"],
                "21,99",
            ),
            "65,80",
        )
        self.assertEqual(
            Shopee._extract_old_price_from_lines(
                ["Fone Bluetooth", "R$ 21,99"],
                "21,99",
            ),
            "",
        )

    def test_shopee_extrai_cards_com_multiplos_seletores(self):

        store = Shopee()

        class FakePage:
            class Locator:
                @staticmethod
                def evaluate_all(_script):
                    return [
                        {
                            "href": "https://shopee.com.br/produto-i.12345.67890",
                            "text": "Fone Bluetooth\nR$\n21,99",
                            "image": "https://susercontent.com/img.jpg",
                            "imageAlt": "Fone Bluetooth Sem Fio",
                        }
                    ]

            def locator(self, selector):
                return self.Locator()

        cards = store._extract_cards(FakePage())
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["href"], "https://shopee.com.br/produto-i.12345.67890")

    def test_shopee_extrai_cards_retorna_vazio_quando_sem_resultados(self):

        store = Shopee()

        class FakePage:
            class Locator:
                @staticmethod
                def evaluate_all(_script):
                    return []

            def locator(self, selector):
                return self.Locator()

        cards = store._extract_cards(FakePage())
        self.assertEqual(cards, [])

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
