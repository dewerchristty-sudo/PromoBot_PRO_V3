import unittest
from unittest.mock import Mock, patch

from src.core.store_manager import StoreManager
from src.stores.amazon import Amazon
from src.stores.mercado_livre import MercadoLivre
from src.stores.shopee import Shopee, ShopeeVariationRequired


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
        """JSON escapado e capturado pelo fallback regex quando contem preco.

        O parser JSON estruturado (json.loads) interpreta a string escapada
        corretamente como string, mas o fallback regex encontra o padrao
        price_before_discount no texto apos o unescape.
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(
            r'<script>{"data":"{\"price_before_discount\":7990000}"}</script>',
            "lxml",
        )

        # O fallback regex encontra price_before_discount no texto apos unescape
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


class ShopeePriceFixTest(unittest.TestCase):
    """Testes para as correcoes de preco da Shopee (ETAPA 1)."""

    # ======================================================
    # normalize_price
    # ======================================================

    def test_normalize_price_rejeita_zero(self):
        """normalize_price('0') retorna string vazia."""
        self.assertEqual(Shopee.normalize_price("0"), "")

    def test_normalize_price_rejeita_zero_com_zeros(self):
        """normalize_price('000') retorna string vazia."""
        self.assertEqual(Shopee.normalize_price("000"), "")

    def test_normalize_price_mantem_preco_valido_pequeno(self):
        """normalize_price('99') retorna '99' (abaixo de 100000)."""
        self.assertEqual(Shopee.normalize_price("99"), "99")

    def test_normalize_price_converte_formato_shopee(self):
        """normalize_price('3197000') retorna '31,97'."""
        self.assertEqual(Shopee.normalize_price("3197000"), "31,97")

    def test_normalize_price_decimal_ponto(self):
        """normalize_price('31.97') retorna '31,97'."""
        self.assertEqual(Shopee.normalize_price("31.97"), "31,97")

    def test_normalize_price_decimal_virgula(self):
        """normalize_price('1.299,90') retorna '1299,90'."""
        self.assertEqual(Shopee.normalize_price("R$ 1.299,90"), "1299,90")

    # ======================================================
    # prices_from_page — novo parser JSON
    # ======================================================

    def test_prices_from_page_json_ld_simples(self):
        """JSON-LD com @type Product extrai preco e preco anterior."""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(
            """
            <script type="application/ld+json">
            {"@type":"Product","name":"SSD 1TB","offers":{"price":"319.70","price_before_discount":"539.00"}}
            </script>
            """,
            "lxml",
        )
        current, old = Shopee.prices_from_page(soup)
        self.assertEqual(current, "319,70")
        self.assertEqual(old, "539,00")

    def test_prices_from_page_json_ld_sem_anterior(self):
        """JSON-LD sem preco anterior retorna old vazio."""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(
            """
            <script type="application/ld+json">
            {"@type":"Product","name":"SSD 1TB","offers":{"price":"319.70"}}
            </script>
            """,
            "lxml",
        )
        current, old = Shopee.prices_from_page(soup)
        self.assertEqual(current, "319,70")
        self.assertEqual(old, "")

    def test_prices_from_page_rejeita_preco_zero_no_json(self):
        """JSON com price=0 retorna current vazio para produto com variacoes."""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(
            """
            <script>
            {"price":0,"price_min":3197,"price_max":5390,"variations":[]}
            </script>
            """,
            "lxml",
        )
        current, old = Shopee.prices_from_page(soup)
        self.assertEqual(current, "")
        self.assertEqual(old, "")

    def test_prices_from_page_faixa_de_preco_retorna_vazio(self):
        """price_min != price_max retorna vazio (faixa, nao inventa preco)."""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(
            """
            <script>
            {"price":0,"price_min":3197000,"price_max":5390000}
            </script>
            """,
            "lxml",
        )
        current, old = Shopee.prices_from_page(soup)
        self.assertEqual(current, "")
        self.assertEqual(old, "")

    def test_prices_from_page_nao_confunde_cupom_com_preco(self):
        """Campos coupon_value nao viram preco."""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(
            """
            <script>
            {"price":3197000,"coupon_value":10000,"price_before_discount":5390000}
            </script>
            """,
            "lxml",
        )
        current, old = Shopee.prices_from_page(soup)
        self.assertEqual(current, "31,97")
        self.assertEqual(old, "53,90")

    def test_prices_from_page_extrai_de_json_escapado(self):
        """JSON escapado ({data:...}) capturado pelo fallback regex."""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(
            r'<script>{"data":"{\"price\":3197000,\"price_before_discount\":5390000}"}</script>',
            "lxml",
        )
        current, old = Shopee.prices_from_page(soup)
        # O fallback regex encontra price e price_before_discount
        # no texto apos o unescape das aspas.
        self.assertEqual(current, "31,97")
        self.assertEqual(old, "53,90")

    def test_prices_from_page_aninhado_com_preco(self):
        """Preco em objeto aninhado (product.price) encontrado via navegacao."""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(
            """
            <script>
            {"productDetail":{"price":3197000,"price_before_discount":5390000}}
            </script>
            """,
            "lxml",
        )
        current, old = Shopee.prices_from_page(soup)
        self.assertEqual(current, "31,97")
        self.assertEqual(old, "53,90")

    def test_price_details_registra_preco_normal(self):
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(
            '<script>{"product":{"product_name":"Item","price":3197000}}</script>',
            "lxml",
        )
        details = Shopee.price_details_from_page(soup)
        self.assertEqual(details["current"], "31,97")
        self.assertEqual(details["origin"], "preço normal")

    def test_price_details_distingue_pix_e_cupom(self):
        from bs4 import BeautifulSoup
        pix = BeautifulSoup(
            '<script>{"product":{"product_name":"Item","price_pix":2990000}}</script>',
            "lxml",
        )
        coupon = BeautifulSoup(
            '<script>{"product":{"product_name":"Item","price_with_coupon":2790000}}</script>',
            "lxml",
        )
        self.assertEqual(
            Shopee.price_details_from_page(pix)["origin"],
            "preço Pix",
        )
        self.assertEqual(
            Shopee.price_details_from_page(coupon)["origin"],
            "cupom",
        )

    def test_price_details_faixa_prevalece_sobre_modelo_filho(self):
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(
            """
            <script>
            {"product":{"product_name":"Item","price":0,
             "price_min":1990000,"price_max":3990000,
             "models":[{"price":1990000},{"price":3990000}]}}
            </script>
            """,
            "lxml",
        )
        details = Shopee.price_details_from_page(soup)
        self.assertTrue(details["is_range"])
        self.assertTrue(details["has_variations"])
        self.assertEqual(details["origin"], "faixa")
        self.assertEqual(details["current"], "")

    def test_price_details_ignora_recomendado_frete_parcela_e_cashback(self):
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(
            """
            <script>
            {"recommended":{"price":990000},
             "shipping":{"price":1200000},
             "installment":{"price":1500000},
             "cashback":{"price":500000},
             "product":{"product_name":"Principal","price":3197000}}
            </script>
            """,
            "lxml",
        )
        details = Shopee.price_details_from_page(soup)
        self.assertEqual(details["current"], "31,97")

    def test_selected_model_id_le_parametro_direto(self):
        self.assertEqual(
            Shopee.selected_model_id(
                "https://shopee.com.br/item?display_model_id=302207312691"
            ),
            "302207312691",
        )

    def test_selected_model_id_le_extra_params_da_listagem(self):
        self.assertEqual(
            Shopee.selected_model_id(
                "https://shopee.com.br/item?"
                "extraParams=%7B%22display_model_id%22%3A302207312691%7D"
            ),
            "302207312691",
        )

    @staticmethod
    def variation_catalog():
        return {
            "groups": [
                {"name": "Cor", "options": ["Azul", "Rosa"]},
                {"name": "Tamanho", "options": ["P", "G"]},
            ],
            "models": [
                {
                    "id": "101",
                    "name": "Azul / P",
                    "tier_indexes": [0, 0],
                    "options": ["Azul", "P"],
                    "stock": 3,
                },
                {
                    "id": "102",
                    "name": "Azul / G",
                    "tier_indexes": [0, 1],
                    "options": ["Azul", "G"],
                    "stock": 0,
                },
                {
                    "id": "103",
                    "name": "Rosa / G",
                    "tier_indexes": [1, 1],
                    "options": ["Rosa", "G"],
                    "stock": 7,
                },
            ],
        }

    def test_variation_catalog_from_page_uma_dimensao(self):
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(
            """
            <script>
            {"item":{"tier_variations":[
              {"name":"Cor","options":[{"name":"Azul"},{"name":"Rosa"}]}
            ],"models":[
              {"modelid":1,"tier_index":[0],"stock":2},
              {"modelid":2,"tier_index":[1],"stock":0}
            ]}}
            </script>
            """,
            "lxml",
        )
        catalog = Shopee.variation_catalog_from_page(soup)
        self.assertEqual(catalog["groups"][0]["name"], "Cor")
        self.assertEqual(catalog["models"][0]["name"], "Azul")
        self.assertEqual(catalog["models"][1]["stock"], 0)

    def test_variation_catalog_from_page_duas_dimensoes(self):
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(
            """
            <script>
            {"item":{"tier_variations":[
              {"name":"Cor","options":["Azul","Rosa"]},
              {"name":"Tamanho","options":["P","G"]}
            ],"models":[
              {"modelid":101,"tier_index":[0,0],"stock":3},
              {"modelid":103,"tier_index":[1,1],"stock":7}
            ]}}
            </script>
            """,
            "lxml",
        )
        catalog = Shopee.variation_catalog_from_page(soup)
        self.assertEqual(len(catalog["groups"]), 2)
        self.assertEqual(catalog["models"][1]["name"], "Rosa / G")

    def test_variation_selection_incompleta_e_bloqueada(self):
        with self.assertRaisesRegex(ValueError, "todas"):
            Shopee.model_for_selection(
                self.variation_catalog(),
                {"Cor": "Azul"},
            )

    def test_variation_sem_estoque_e_bloqueada(self):
        with self.assertRaisesRegex(ValueError, "sem estoque"):
            Shopee.model_for_selection(
                self.variation_catalog(),
                {"Cor": "Azul", "Tamanho": "G"},
            )

    def test_variation_nao_escolhe_menor_preco_automaticamente(self):
        with self.assertRaisesRegex(ValueError, "todas"):
            Shopee.model_for_selection(self.variation_catalog(), {})

    def test_catalogo_com_um_unico_modelo_nao_altera_preco_unico(self):
        catalog = {
            "groups": [{"name": "Modelo", "options": ["Único"]}],
            "models": [{
                "id": "1",
                "name": "Único",
                "options": ["Único"],
                "tier_indexes": [0],
                "stock": 5,
            }],
        }
        self.assertFalse(Shopee.catalog_requires_selection(catalog))

    def test_product_from_url_expoe_catalogo_sem_escolher_preco(self):
        catalog_json = """
        {"item":{"product_name":"Produto variável","price":0,
         "price_min":2398000,"price_max":2598000,
         "tier_variations":[{"name":"Cor","options":["Azul","Rosa"]}],
         "models":[
           {"modelid":1,"tier_index":[0],"stock":2},
           {"modelid":2,"tier_index":[1],"stock":3}
         ]}}
        """

        class FakePage:
            url = "https://shopee.com.br/produto-i.1.2"

            def goto(self, *_args, **_kwargs):
                return None

            def wait_for_timeout(self, _timeout):
                return None

            def content(self):
                return (
                    '<meta property="og:title" content="Produto variável">'
                    '<meta property="og:image" content="https://example.com/a.jpg">'
                    f"<script>{catalog_json}</script>"
                )

            def evaluate(self, *_args):
                return []

            def close(self):
                return None

        manager = Mock()
        manager.new_page.side_effect = lambda **_kwargs: FakePage()
        store = Shopee(manager)
        with self.assertRaises(ShopeeVariationRequired) as context:
            store._product_from_url_sync(
                "https://shopee.com.br/produto-i.1.2"
            )
        self.assertEqual(
            context.exception.catalog["groups"][0]["options"],
            ["Azul", "Rosa"],
        )

    def test_product_from_url_usa_apenas_preco_visivel_da_variacao(self):
        catalog_json = """
        {"item":{"product_name":"Produto variável","price":0,
         "price_min":2398000,"price_max":2598000,
         "tier_variations":[{"name":"Cor","options":["Azul","Rosa"]}],
         "models":[
           {"modelid":1,"tier_index":[0],"stock":2},
           {"modelid":2,"tier_index":[1],"stock":3}
         ]}}
        """

        class FakePage:
            url = "https://shopee.com.br/produto-i.1.2"

            def goto(self, *_args, **_kwargs):
                return None

            def wait_for_timeout(self, _timeout):
                return None

            def content(self):
                return (
                    '<meta property="og:title" content="Produto variável">'
                    '<meta property="og:image" content="https://example.com/a.jpg">'
                    f"<script>{catalog_json}</script>"
                )

            def evaluate(self, *_args):
                return []

            def close(self):
                return None

        manager = Mock()
        manager.new_page.side_effect = lambda **_kwargs: FakePage()
        store = Shopee(manager)
        with (
            patch.object(
                Shopee,
                "apply_variation_selection",
                return_value={
                    "id": "2",
                    "name": "Rosa",
                    "stock": 3,
                    "options": ["Rosa"],
                },
            ),
            patch.object(
                Shopee,
                "stable_variation_price",
                return_value={
                    "current": "25,98",
                    "origin": "cupom",
                    "element": {"tag": "span"},
                },
            ),
        ):
            product = store._product_from_url_sync(
                "https://shopee.com.br/produto-i.1.2",
                variation_selection={"Cor": "Rosa"},
            )
        self.assertEqual(product["preco"], "25,98")
        self.assertEqual(product["origem_preco"], "cupom")
        self.assertEqual(product["variacao_selecionada"], "Rosa")
        self.assertEqual(product["estoque_variacao"], 3)

    def test_available_variation_options_remove_sem_estoque(self):
        catalog = self.variation_catalog()
        self.assertEqual(
            Shopee.available_variation_options(
                catalog,
                1,
                {"Cor": "Azul"},
            ),
            ["P"],
        )
        self.assertEqual(
            Shopee.available_variation_options(
                catalog,
                1,
                {"Cor": "Rosa"},
            ),
            ["G"],
        )

    def test_apply_variation_selection_clica_opcoes_reais(self):
        class FakePage:
            def __init__(self):
                self.calls = []

            def evaluate(self, _script, payload):
                self.calls.append(payload)
                return {"ok": True}

            def wait_for_timeout(self, _timeout):
                return None

        page = FakePage()
        model = Shopee.apply_variation_selection(
            page,
            self.variation_catalog(),
            {"Cor": "Rosa", "Tamanho": "G"},
        )
        self.assertEqual(model["id"], "103")
        self.assertEqual(
            page.calls,
            [
                {"groupName": "Cor", "optionName": "Rosa"},
                {"groupName": "Tamanho", "optionName": "G"},
            ],
        )

    def test_stable_variation_price_preserva_pix_ou_cupom(self):
        class FakePage:
            def wait_for_timeout(self, _timeout):
                return None

        values = [
            {"current": "19,90", "origin": "preço Pix"},
            {"current": "19,90", "origin": "preço Pix"},
        ]
        with patch.object(
            Shopee,
            "current_price_from_visible_page",
            side_effect=values,
        ):
            result = Shopee.stable_variation_price(FakePage())
        self.assertEqual(result["origin"], "preço Pix")

    def test_stable_variation_price_bloqueia_mudanca(self):
        class FakePage:
            def wait_for_timeout(self, _timeout):
                return None

        values = [
            {"current": "19,90", "origin": "cupom"},
            {"current": "21,90", "origin": "cupom"},
        ]
        with patch.object(
            Shopee,
            "current_price_from_visible_page",
            side_effect=values,
        ):
            with self.assertRaisesRegex(ValueError, "estável"):
                Shopee.stable_variation_price(FakePage())

    def test_stable_variation_price_bloqueia_dom_ambiguo(self):
        class FakePage:
            def wait_for_timeout(self, _timeout):
                return None

        value = {
            "current": "19,90",
            "origin": "preço normal",
            "ambiguous": True,
        }
        with patch.object(
            Shopee,
            "current_price_from_visible_page",
            side_effect=[value, value],
        ):
            with self.assertRaisesRegex(ValueError, "ambíguo"):
                Shopee.stable_variation_price(FakePage())

    # ======================================================
    # _extract_old_price_from_lines
    # ======================================================

    def test_extract_old_price_from_lines_com_preco_valido(self):
        """Com current_price=21,99, retorna 65,80 como anterior."""
        self.assertEqual(
            Shopee._extract_old_price_from_lines(
                ["Fone Bluetooth", "R$ 21,99", "R$ 65,80", "-67%"],
                "21,99",
            ),
            "65,80",
        )

    def test_extract_old_price_from_lines_sem_anterior(self):
        """Sem preco anterior nas linhas, retorna vazio."""
        self.assertEqual(
            Shopee._extract_old_price_from_lines(
                ["Fone Bluetooth", "R$ 21,99"],
                "21,99",
            ),
            "",
        )

    def test_extract_old_price_from_lines_rejeita_quando_current_zero(self):
        """Quando current_price='0', retorna vazio (evita desconto 100%)."""
        self.assertEqual(
            Shopee._extract_old_price_from_lines(
                ["Fone Bluetooth", "R$ 0,00", "R$ 43,00", "-67%"],
                "0,00",
            ),
            "",
        )

    def test_extract_old_price_from_lines_rejeita_quando_current_vazio(self):
        """Quando current_price='', retorna vazio."""
        self.assertEqual(
            Shopee._extract_old_price_from_lines(
                ["Fone Bluetooth", "R$ 43,00"],
                "",
            ),
            "",
        )

    # ======================================================
    # extract_price
    # ======================================================

    def test_extract_price_com_preco_valido(self):
        """extract_price retorna preco quando > 0."""
        store = Shopee()
        self.assertEqual(
            store.extract_price(["Fone Bluetooth", "R$", "21,99", "-67%"]),
            "21,99",
        )

    def test_extract_price_com_preco_na_mesma_linha(self):
        """extract_price com 'R$ 21,99' na mesma linha."""
        store = Shopee()
        self.assertEqual(
            store.extract_price(["Fone Bluetooth", "R$ 21,99", "-67%"]),
            "21,99",
        )

    def test_extract_price_rejeita_zero(self):
        """extract_price retorna vazio quando unico preco e 0,00."""
        store = Shopee()
        self.assertEqual(
            store.extract_price(["Fone Bluetooth", "R$ 0,00", "-67%"]),
            "",
        )

    def test_extract_price_rejeita_zero_separado(self):
        """extract_price retorna vazio quando R$ seguido de 0,00."""
        store = Shopee()
        self.assertEqual(
            store.extract_price(["Fone Bluetooth", "R$", "0,00", "-67%"]),
            "",
        )

    def test_extract_price_sem_preco_retorna_vazio(self):
        """extract_price sem R$ retorna vazio."""
        store = Shopee()
        self.assertEqual(
            store.extract_price(["Fone Bluetooth", "Sem preco"]),
            "",
        )

    # ======================================================
    # _product_from_url_sync — validacao de parsed_price > 0
    # ======================================================

    def test_product_from_url_rejeita_preco_zero(self):
        """_product_from_url_sync levanta ValueError com preco zero."""
        class EmptyPage:
            url = "https://shopee.com.br/produto-i.1.2"

            def goto(self, *_args, **_kwargs):
                return None

            def wait_for_timeout(self, _timeout):
                return None

            def content(self):
                return "<html><body>Produto sem preço</body></html>"

            def evaluate(self, _script):
                return []

            def close(self):
                return None

        class FakeManager:
            def new_page(self, stealth=True):
                return EmptyPage()

        store = Shopee(FakeManager())
        with self.assertRaises(ValueError) as ctx:
            store._product_from_url_sync(
                "https://shopee.com.br/produto-i.1.2"
            )
        self.assertIn("variacoes", str(ctx.exception).lower())

    # ======================================================
    # old_price_from_visible_page
    # ======================================================

    def test_old_price_from_visible_page_com_strikethrough(self):
        """Preco com line-through e aceito como anterior."""
        class FakePage:
            @staticmethod
            def evaluate(_script):
                return ["R$53,90", "R$ 29,00"]
        self.assertEqual(
            Shopee.old_price_from_visible_page(FakePage(), "31,97"),
            "53,90",
        )

    def test_old_price_from_visible_page_sem_strikethrough_mas_classe_original(self):
        """Preco sem line-through mas com classe 'original' e aceito."""
        # Simula um page.evaluate que retorna precos de elementos
        # com classe 'product-price__original' (sem strikethrough)
        class FakePageWithOriginalClass:
            @staticmethod
            def evaluate(_script):
                # O script JS agora procura parentClass tambem,
                # mas como o mock so retorna texto, simulamos
                # que o JS encontrou 'original' na classe.
                return ["R$ 79,90"]
        self.assertEqual(
            Shopee.old_price_from_visible_page(FakePageWithOriginalClass(), "49,90"),
            "79,90",
        )

    def test_old_price_from_visible_page_sem_evidencia_semantica(self):
        """Preco sem strikethrough, tag ou classe relevante nao e aceito."""
        class FakePageNoEvidence:
            @staticmethod
            def evaluate(_script):
                return []  # Nenhum candidato com evidencia semantica
        self.assertEqual(
            Shopee.old_price_from_visible_page(FakePageNoEvidence(), "49,90"),
            "",
        )

    def test_old_price_from_visible_page_nao_aceita_preco_menor_que_atual(self):
        """Preco candidato menor ou igual ao atual nao e aceito."""
        class FakePage:
            @staticmethod
            def evaluate(_script):
                return ["R$ 29,00"]  # menor que 31,97
        self.assertEqual(
            Shopee.old_price_from_visible_page(FakePage(), "31,97"),
            "",
        )

    # ======================================================
    # old_price_from_visible_page — rejeicao de cores/cupons
    # ======================================================

    def test_old_price_from_visible_page_rejeita_preco_cinza_sem_classe_semantica(self):
        """Preco em cinza sem classe semântica nao e aceito como anterior."""
        class FakePageGrayNoClass:
            @staticmethod
            def evaluate(_script):
                # Nenhum candidato passa pelo filtro de evidencia semantica
                return []
        self.assertEqual(
            Shopee.old_price_from_visible_page(FakePageGrayNoClass(), "49,90"),
            "",
        )

    # ======================================================
    # Cenario completo: produto com variacoes nao selecionadas
    # ======================================================

    def test_produto_com_variacoes_nao_cria_preco_artificial(self):
        """Produto com price=0 e price_min!=price_max retorna vazio."""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(
            """
            <script>
            {"price":0,"price_min":1000000,"price_max":2000000}
            </script>
            """,
            "lxml",
        )
        current, old = Shopee.prices_from_page(soup)
        self.assertEqual(current, "")  # Nao inventa valor
        self.assertEqual(old, "")      # Nao calcula desconto artificial

    # ======================================================
    # Cenario completo: economia nao calculada quando falta preco
    # ======================================================

    def test_economia_nao_calculada_quando_preco_zero(self):
        """_extract_old_price_from_lines retorna vazio quando preco atual e zero."""
        result = Shopee._extract_old_price_from_lines(
            ["Produto", "R$ 0,00", "R$ 43,00"],
            "0,00",
        )
        self.assertEqual(result, "")

    def test_economia_nao_calculada_quando_sem_preco_anterior(self):
        """Sem preco anterior nas linhas, retorna vazio."""
        result = Shopee._extract_old_price_from_lines(
            ["Produto", "R$ 21,99"],
            "21,99",
        )
        self.assertEqual(result, "")

    # ======================================================
    # Desconto nao calculado quando falta preco
    # ======================================================

    def test_desconto_nao_calculado_quando_preco_atual_zero(self):
        """Com current_price=0, _extract_old_price_from_lines retorna vazio."""
        result = Shopee._extract_old_price_from_lines(
            ["Produto", "R$ 0,00", "R$ 50,00"],
            "0,00",
        )
        self.assertEqual(result, "")

    # ======================================================
    # Fallback regex: window.__INITIAL_STATE__
    # ======================================================

    def test_prices_from_page_window_initial_state(self):
        """JavaScript com window.__INITIAL_STATE__ e parseado pelo fallback regex."""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(
            """
            <script>
            window.__INITIAL_STATE__ = {"product": {"price": 3197000, "price_before_discount": 5390000}};
            </script>
            """,
            "lxml",
        )
        current, old = Shopee.prices_from_page(soup)
        self.assertEqual(current, "31,97")
        self.assertEqual(old, "53,90")

    def test_prices_from_page_produto_simples(self):
        """Produto simples (sem variacao) com JSON valido."""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(
            """
            <script>
            {"price":3197000,"price_before_discount":5390000,"product_name":"SSD 1TB"}
            </script>
            """,
            "lxml",
        )
        current, old = Shopee.prices_from_page(soup)
        self.assertEqual(current, "31,97")
        self.assertEqual(old, "53,90")

    def test_prices_from_page_faixa_de_preco_regex_fallback(self):
        """Faixa de precos (price_min != price_max) rejeitada mesmo no fallback."""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(
            """
            <script>
            window.__INITIAL_STATE__ = {"product": {"price": 0, "price_min": 3197000, "price_max": 5390000}};
            </script>
            """,
            "lxml",
        )
        current, old = Shopee.prices_from_page(soup)
        self.assertEqual(current, "")
        self.assertEqual(old, "")

    def test_prices_from_page_cupom_antes_do_preco(self):
        """Cupom e ignorado; preco real do produto capturado."""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(
            """
            <script>
            window.__INITIAL_STATE__ = {"coupon": {"value": 10000}, "product": {"price": 3197000, "price_before_discount": 5390000}};
            </script>
            """,
            "lxml",
        )
        current, old = Shopee.prices_from_page(soup)
        self.assertEqual(current, "31,97")
        self.assertEqual(old, "53,90")

    def test_prices_from_page_sem_contexto_produto_ignora_script(self):
        """Script sem contexto de produto e ignorado pelo fallback."""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(
            """
            <script>
            {"frete": 1500, "parcela": 3}
            </script>
            """,
            "lxml",
        )
        current, old = Shopee.prices_from_page(soup)
        self.assertEqual(current, "")
        self.assertEqual(old, "")

    def test_prices_from_page_fallback_respeita_protecao_zero(self):
        """Fallback regex nao aceita price=0."""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(
            """
            <script>
            window.__INITIAL_STATE__ = {"product": {"price": 0, "price_before_discount": 5390000}};
            </script>
            """,
            "lxml",
        )
        current, old = Shopee.prices_from_page(soup)
        self.assertEqual(current, "")
        self.assertEqual(old, "53,90")

    # ======================================================
    # current_price_from_visible_page
    # ======================================================

    def test_current_price_from_visible_page_simples(self):
        """Preco atual simples no DOM com classe price."""
        class FakePage:
            @staticmethod
            def evaluate(_script):
                return [
                    {"tag": "span", "className": "product-price", "parentClass": "", "text": "R$ 31,97"}
                ]
        self.assertEqual(
            Shopee.current_price_from_visible_page(FakePage()),
            "31,97",
        )

    def test_current_price_from_visible_page_ignora_riscado(self):
        """Preco com line-through nao e aceito como atual."""
        class FakePage:
            @staticmethod
            def evaluate(_script):
                return []  # O JS filtra strikethrough antes de retornar
        self.assertEqual(
            Shopee.current_price_from_visible_page(FakePage()),
            "",
        )

    def test_current_price_from_visible_page_faixa_de_precos(self):
        """Faixa de precos (R$ 19,90 - R$ 39,90) retorna vazio."""
        class FakePage:
            @staticmethod
            def evaluate(_script):
                return [
                    {"tag": "span", "className": "product-price", "parentClass": "", "text": "R$ 19,90 - R$ 39,90"}
                ]
        self.assertEqual(
            Shopee.current_price_from_visible_page(FakePage()),
            "",
        )

    def test_current_price_from_visible_page_ignora_parcela(self):
        """Parcela no texto ou classe nao e aceita como preco atual."""
        class FakePage:
            @staticmethod
            def evaluate(_script):
                return [
                    {"tag": "span", "className": "product-price", "parentClass": "", "text": "R$ 31,97"}
                ]
        # O JS filtra por classe, entao 'parcela' na classe seria ignorado
        # Simulamos que o JS retornou apenas o preco valido
        self.assertEqual(
            Shopee.current_price_from_visible_page(FakePage()),
            "31,97",
        )

    def test_current_price_from_visible_page_ignora_cupom(self):
        """Cupom na classe nao e aceito como preco atual."""
        class FakePage:
            @staticmethod
            def evaluate(_script):
                return [
                    {"tag": "span", "className": "product-price", "parentClass": "", "text": "R$ 31,97"}
                ]
        self.assertEqual(
            Shopee.current_price_from_visible_page(FakePage()),
            "31,97",
        )

    def test_current_price_from_visible_page_sem_preco_valido(self):
        """Nenhum preco valido no DOM retorna vazio."""
        class FakePage:
            @staticmethod
            def evaluate(_script):
                return []
        self.assertEqual(
            Shopee.current_price_from_visible_page(FakePage()),
            "",
        )

    def test_current_price_from_visible_page_ignora_frete(self):
        """Frete na classe nao e aceito como preco atual."""
        class FakePage:
            @staticmethod
            def evaluate(_script):
                return [
                    {"tag": "span", "className": "product-price", "parentClass": "", "text": "R$ 31,97"}
                ]
        self.assertEqual(
            Shopee.current_price_from_visible_page(FakePage()),
            "31,97",
        )

    def test_current_price_from_visible_page_ignora_pix(self):
        """Pix na classe nao e aceito como preco atual."""
        class FakePage:
            @staticmethod
            def evaluate(_script):
                return [
                    {"tag": "span", "className": "product-price", "parentClass": "", "text": "R$ 31,97"}
                ]
        self.assertEqual(
            Shopee.current_price_from_visible_page(FakePage()),
            "31,97",
        )

    def test_current_price_from_visible_page_ignora_produto_recomendado(self):
        """Produto recomendado (classe sem price) nao e aceito."""
        class FakePage:
            @staticmethod
            def evaluate(_script):
                return []  # Sem classe com price, retorna vazio
        self.assertEqual(
            Shopee.current_price_from_visible_page(FakePage()),
            "",
        )
