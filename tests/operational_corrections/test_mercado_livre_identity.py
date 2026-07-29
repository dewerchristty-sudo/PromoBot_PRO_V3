import unittest
from unittest.mock import Mock, patch
from tempfile import TemporaryDirectory
from pathlib import Path

import requests

from src.database.database import Database
from src.stores.mercado_livre import (
    MercadoLivre,
    MercadoLivreAmbiguousIdentity,
    MercadoLivreIdentityType,
    MercadoLivreUnavailableError,
)


PRODUCT_HTML = """
<html><head>
<link rel="canonical" href="{canonical}">
<meta property="og:url" content="{canonical}">
<meta property="og:image" content="https://example.com/product.jpg">
<script type="application/ld+json">
{{"@type":"Product","name":"{title}","sku":"{sku}",
  "offers":{{"price":"{price}"}}}}
</script>
</head><body><h1 class="ui-pdp-title">{title}</h1>
<div class="ui-pdp-price__second-line"><span class="andes-money-amount">
<span class="andes-money-amount__fraction">{fraction}</span>
<span class="andes-money-amount__cents">{cents}</span>
</span></div></body></html>
"""


def product_html(title, canonical, sku, price):
    whole, cents = price.split(".")
    return PRODUCT_HTML.format(
        title=title,
        canonical=canonical,
        sku=sku,
        price=price,
        fraction=whole,
        cents=cents,
    )


class Response:
    def __init__(self, status=200):
        self.status = status


class SequencedPage:
    def __init__(self, entries):
        self.entries = list(entries)
        self.url = ""
        self.current = None
        self.closed = False

    def goto(self, url, **_kwargs):
        self.current = self.entries.pop(0)
        self.url = self.current["url"]
        return Response(self.current.get("status", 200))

    def wait_for_timeout(self, _timeout):
        return None

    def content(self):
        return self.current.get("html", "")

    def title(self):
        return self.current.get("title", "Produto")

    def close(self):
        self.closed = True


class MercadoLivreIdentityTest(unittest.TestCase):
    def test_banco_expoe_identidade_tipificada_sem_normalizar_url(self):
        identity = Database.identidade_mercado_livre_link(
            "https://www.mercadolivre.com.br/tv/p/MLB48954912"
        )
        self.assertEqual(identity["tipo"], "CATALOGO")
        self.assertEqual(identity["id_catalogo"], "MLB48954912")
        self.assertEqual(identity["id_item"], "")

    def test_banco_preserva_urls_e_ids_em_campos_separados(self):
        with TemporaryDirectory() as directory:
            database = Database(Path(directory) / "identity.db")
            original = "https://meli.la/12MQRBY"
            database.salvar_identidade_mercado_livre(
                original,
                original,
                {
                    "tipo": "ITEM",
                    "id_item": "MLB6760718206",
                    "id_catalogo": "MLB48954912",
                    "url_final": (
                        "https://www.mercadolivre.com.br/tv/p/MLB48954912"
                    ),
                    "fonte_da_identidade": "WID+URL_CATALOGO",
                },
            )
            stored = database.buscar_identidade_mercado_livre(original)
            self.assertEqual(stored["link_original"], original)
            self.assertEqual(stored["link_afiliado"], original)
            self.assertEqual(stored["id_item"], "MLB6760718206")
            self.assertEqual(stored["id_catalogo"], "MLB48954912")
            database.conn.close()

    def test_item_id_em_filtro_tem_prioridade_sobre_catalogo(self):
        identity = MercadoLivre.identity_from_url(
            "https://www.mercadolivre.com.br/produto/p/MLB48954912"
            "?pdp_filters=item_id%3AMLB6760718206"
        )
        self.assertEqual(identity.tipo, MercadoLivreIdentityType.ITEM)
        self.assertEqual(identity.id_item, "MLB6760718206")
        self.assertEqual(identity.id_catalogo, "MLB48954912")
        self.assertEqual(identity.fonte_da_identidade, "PDP_FILTERS_ITEM_ID")

    def test_wid_confirmado_identifica_item(self):
        identity = MercadoLivre.identity_from_url(
            "https://www.mercadolivre.com.br/produto/p/MLB46649637"
            "?wid=MLB5306571166"
        )
        self.assertEqual(identity.id_item, "MLB5306571166")
        self.assertEqual(identity.id_catalogo, "MLB46649637")
        self.assertEqual(identity.fonte_da_identidade, "WID")

    def test_item_sem_catalogo(self):
        identity = MercadoLivre.identity_from_url(
            "https://produto.mercadolivre.com.br/MLB-2004756242"
        )
        self.assertEqual(identity.tipo, MercadoLivreIdentityType.ITEM)
        self.assertEqual(identity.id_item, "MLB2004756242")
        self.assertFalse(identity.id_catalogo)

    def test_catalogos_mlb_e_mlbu_nao_viram_item(self):
        mlb = MercadoLivre.identity_from_url(
            "https://www.mercadolivre.com.br/tv/p/MLB48954912"
        )
        mlbu = MercadoLivre.identity_from_url(
            "https://www.mercadolivre.com.br/kit/up/MLBU3489556503"
        )
        self.assertEqual(mlb.tipo, MercadoLivreIdentityType.CATALOGO)
        self.assertEqual(mlb.id_catalogo, "MLB48954912")
        self.assertFalse(mlb.id_item)
        self.assertEqual(mlbu.id_catalogo, "MLBU3489556503")
        self.assertFalse(mlbu.id_item)

    def test_link_principal_destacado_ignora_recomendacoes(self):
        html = """
        <a class="poly-component__title"
           href="https://www.mercadolivre.com.br/tv/p/MLB48954912#polycard_client=x&amp;wid=MLB6760718206&amp;c_id=/home/card-featured/element">
           Produto principal
        </a>
        <a class="poly-component__title"
           href="https://www.mercadolivre.com.br/outro/p/MLB11111111?wid=MLB9999999999#c_id=/home/recommendations/element">
           Recomendado
        </a>
        """
        selected = MercadoLivre.primary_social_product_url(
            html, "https://www.mercadolivre.com.br/social/loja"
        )
        self.assertIn("MLB48954912", selected)
        self.assertNotIn("MLB11111111", selected)

    def test_multiplos_destaques_divergentes_sao_ambiguos(self):
        html = """
        <a class="poly-component__title"
          href="https://www.mercadolivre.com.br/a/p/MLB1?wid=MLB10#c_id=/home/card-featured/element">A</a>
        <a class="poly-component__title"
          href="https://www.mercadolivre.com.br/b/p/MLB2?wid=MLB20#c_id=/home/card-featured/element">B</a>
        """
        with self.assertRaises(MercadoLivreAmbiguousIdentity):
            MercadoLivre.primary_social_product_url(
                html, "https://www.mercadolivre.com.br/social/loja"
            )

    def test_ids_divergentes_entre_url_e_canonical_sao_ambiguos(self):
        origin = MercadoLivre.identity_from_url(
            "https://produto.mercadolivre.com.br/MLB-100"
        )
        final = MercadoLivre.identity_from_url(
            "https://produto.mercadolivre.com.br/MLB-200"
        )
        with self.assertRaises(MercadoLivreAmbiguousIdentity):
            MercadoLivre.reconcile_identity(origin, final, "", final.url_final)

    @patch("src.stores.mercado_livre.requests.get")
    def test_catalogo_sem_item_nunca_chama_api_items(self, request):
        store = MercadoLivre.__new__(MercadoLivre)
        identity = store.identity_from_url(
            "https://www.mercadolivre.com.br/tv/p/MLB48954912"
        )
        with self.assertRaisesRegex(ValueError, "ITEM_NAO_CONFIRMADO"):
            store.product_data_from_api(
                identity.url_final or identity.url_origem,
                identity=identity,
            )
        request.assert_not_called()

    @patch("src.stores.mercado_livre.requests.get")
    def test_api_403_e_reportada_sem_inventar_produto(self, request):
        response = Mock()
        response.raise_for_status.side_effect = requests.HTTPError(
            "403 Client Error"
        )
        request.return_value = response
        store = MercadoLivre.__new__(MercadoLivre)
        identity = store.identity_from_url(
            "https://produto.mercadolivre.com.br/MLB-2004756242"
        )
        with self.assertRaisesRegex(ValueError, "MLB2004756242"):
            store.product_data_from_api(
                identity.url_origem,
                identity=identity,
            )


class MercadoLivreRealCasesRegressionTest(unittest.TestCase):
    def run_case(self, origin, final, html):
        page = SequencedPage([{"url": final, "html": html}])
        manager = Mock()
        manager.new_page.return_value = page
        product = MercadoLivre(browser_manager=manager).product_from_url(origin)
        self.assertTrue(page.closed)
        self.assertEqual(product["ml_classification"], "PRODUTO_RECUPERADO")
        return product

    def test_cozinha_madesa_item_e_catalogo(self):
        canonical = (
            "https://www.mercadolivre.com.br/cozinha/p/MLB21969873"
        )
        product = self.run_case(
            "https://produto.mercadolivre.com.br/MLB-2004756242",
            "https://produto.mercadolivre.com.br/MLB-2004756242-produto-_JM",
            product_html(
                "Cozinha Compacta Madesa", canonical,
                "MLB2004756242", "643.99",
            ),
        )
        self.assertEqual(product["ml_identity"]["id_item"], "MLB2004756242")
        self.assertEqual(product["ml_identity"]["id_catalogo"], "MLB21969873")

    def test_principia_item_e_catalogo_mlbu(self):
        final = (
            "https://www.mercadolivre.com.br/principia/up/MLBU3489556503"
            "?pdp_filters=item_id%3AMLB5806606104"
        )
        product = self.run_case(
            "https://produto.mercadolivre.com.br/MLB-5806606104",
            final,
            product_html(
                "Principia Kit Essencial",
                "https://www.mercadolivre.com.br/principia/up/MLBU3489556503",
                "MLBU3489556503", "118.16",
            ),
        )
        self.assertEqual(product["ml_identity"]["id_item"], "MLB5806606104")
        self.assertEqual(
            product["ml_identity"]["id_catalogo"], "MLBU3489556503"
        )

    def social_case(self, catalog, item, title, price):
        social = f"""
        <a class="poly-component__title"
          href="https://www.mercadolivre.com.br/produto/p/{catalog}?wid={item}#c_id=/home/card-featured/element">
          {title}
        </a>
        <a class="poly-component__title"
          href="https://www.mercadolivre.com.br/recomendado/p/MLB111?wid=MLB999#c_id=/home/recommendations/element">
          Recomendado
        </a>
        """
        final = (
            f"https://www.mercadolivre.com.br/produto/p/{catalog}"
            f"?pdp_filters=item_id%3A{item}"
        )
        page = SequencedPage([
            {
                "url": "https://www.mercadolivre.com.br/social/loja",
                "html": social,
            },
            {
                "url": final,
                "html": product_html(
                    title,
                    f"https://www.mercadolivre.com.br/produto/p/{catalog}",
                    catalog,
                    price,
                ),
            },
        ])
        manager = Mock()
        manager.new_page.return_value = page
        with patch("src.stores.mercado_livre.requests.get") as request:
            product = MercadoLivre(browser_manager=manager).product_from_url(
                "https://meli.la/oficial"
            )
        request.assert_not_called()
        self.assertEqual(product["ml_identity"]["id_item"], item)
        self.assertEqual(product["ml_identity"]["id_catalogo"], catalog)
        self.assertEqual(product["ml_classification"], "PRODUTO_RECUPERADO")
        return product

    def test_smart_tv_recupera_sem_api(self):
        product = self.social_case(
            "MLB48954912", "MLB6760718206", "Smart TV Samsung", "959.40"
        )
        self.assertEqual(product["preco"], "959,40")

    def test_rack_madesa_recupera_sem_api(self):
        product = self.social_case(
            "MLB46649637", "MLB5306571166", "Rack Madesa Dubai", "411.75"
        )
        self.assertEqual(product["preco"], "411,75")

    def test_pagina_realmente_removida_continua_rejeitada(self):
        page = SequencedPage([{
            "url": "https://produto.mercadolivre.com.br/MLB-123",
            "html": "<h1>Página não encontrada</h1>",
            "status": 404,
        }])
        manager = Mock()
        manager.new_page.return_value = page
        with self.assertRaises(MercadoLivreUnavailableError):
            MercadoLivre(browser_manager=manager).product_from_url(page.url)

    def test_falha_nao_vaza_produto_anterior(self):
        store = MercadoLivre.__new__(MercadoLivre)
        good = store.product_data_from_html(
            product_html(
                "Produto anterior",
                "https://www.mercadolivre.com.br/a/p/MLB1",
                "MLB1",
                "10.00",
            ),
            "https://www.mercadolivre.com.br/a/p/MLB1",
        )
        self.assertEqual(good["titulo"], "Produto anterior")
        with self.assertRaises(ValueError):
            store.product_data_from_html("<html></html>", "")


if __name__ == "__main__":
    unittest.main()
