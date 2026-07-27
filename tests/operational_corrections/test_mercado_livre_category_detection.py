from pathlib import Path
import tempfile
import unittest

from bs4 import BeautifulSoup

from src.core.notifier import Notifier
from src.database.database import Database
from src.stores.mercado_livre import MercadoLivre


class MercadoLivreCategoryDetectionTest(unittest.TestCase):

    def product(self, **changes):
        value = {
            "loja": "Mercado Livre",
            "titulo": "Produto sem palavra classificável",
            "link": "https://produto.mercadolivre.com.br/MLB-900000001",
            "breadcrumb": "Informática > Componentes para PC > SSD",
            "categoria_original": "SSD",
        }
        value.update(changes)
        return value

    def test_extrai_breadcrumb_visual_da_pagina(self):
        soup = BeautifulSoup("""
            <ol class="andes-breadcrumb">
              <li class="andes-breadcrumb__item">Informática</li>
              <li class="andes-breadcrumb__item">Armazenamento</li>
              <li class="andes-breadcrumb__item">SSD</li>
            </ol>
        """, "lxml")
        self.assertEqual(
            MercadoLivre.breadcrumb_from_soup(soup),
            ("Informática", "Armazenamento", "SSD"),
        )

    def test_fallback_breadcrumb_json_ld(self):
        soup = BeautifulSoup("""
          <script type="application/ld+json">
          {"@type":"BreadcrumbList","itemListElement":[
            {"@type":"ListItem","name":"Informática"},
            {"@type":"ListItem","item":{"name":"SSD"}}
          ]}
          </script>
        """, "lxml")
        self.assertEqual(
            MercadoLivre.breadcrumb_from_soup(soup),
            ("Informática", "SSD"),
        )

    def test_breadcrumb_ml_encontra_categoria_canonica(self):
        notifier = Notifier()
        category, trace = notifier.detect_mercado_livre_category(
            self.product()
        )
        self.assertEqual(category, "smartphones_tecnologia")
        self.assertEqual(
            trace["function"], "Notifier.detect_mercado_livre_category"
        )
        self.assertEqual(
            trace["rule"], "MERCADO_LIVRE_BREADCRUMB_KEYWORDS"
        )
        self.assertIn("matched:smartphones_tecnologia:ssd", trace["comparison"])

    def test_breadcrumb_valido_sem_mapa_nao_e_nao_detectado(self):
        diagnostic = Notifier().category_routing_diagnostic(self.product(
            breadcrumb="Moda > Masculino > Calças",
            categoria_original="Calças",
        ))
        self.assertEqual(diagnostic["detected_category"], "Calças")
        self.assertEqual(diagnostic["canonical_category"], "")
        self.assertEqual(diagnostic["reason"], "CATEGORY_NOT_MAPPED")
        self.assertNotEqual(diagnostic["reason"], "CATEGORY_NOT_DETECTED")

    def test_sem_breadcrumb_e_sem_categoria_continua_nao_detectado(self):
        diagnostic = Notifier().category_routing_diagnostic(self.product(
            breadcrumb="", categoria_original=""
        ))
        self.assertEqual(diagnostic["reason"], "CATEGORY_NOT_DETECTED")
        self.assertEqual(
            diagnostic["failed_comparison"],
            "breadcrumb_and_original_category_empty",
        )

    def test_persistencia_preserva_taxonomia_ml(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "test.db")
            database.salvar_produto({
                **self.product(),
                "preco": "199,90",
                "imagem": "https://example.com/product.jpg",
            })
            saved = dict(database.buscar_produto_por_link(
                self.product()["link"]
            ))
            database.conn.close()
        self.assertEqual(
            saved["breadcrumb"], "Informática > Componentes para PC > SSD"
        )
        self.assertEqual(saved["categoria_original"], "SSD")

    def test_amazon_e_shopee_nao_usam_detector_ml(self):
        notifier = Notifier()
        for store in ("Amazon", "Shopee"):
            with self.subTest(store=store):
                diagnostic = notifier.category_routing_diagnostic({
                    **self.product(),
                    "loja": store,
                    "link": "https://example.com/product",
                    "breadcrumb": "Informática > SSD",
                    "titulo": "Produto sem classificação xyz",
                })
                self.assertEqual(
                    diagnostic["detector_function"],
                    "Notifier.whatsapp_category",
                )
                self.assertEqual(
                    diagnostic["reason"], "CATEGORY_NOT_DETECTED"
                )

    def test_log_registra_pipeline_completo_sem_html(self):
        with self.assertLogs("src.core.notifier", level="INFO") as captured:
            Notifier().category_routing_diagnostic(self.product())
        log = "\n".join(captured.output)
        self.assertIn("store=Mercado Livre", log)
        self.assertIn("original_url=https://produto.mercadolivre.com.br/", log)
        self.assertIn(
            "breadcrumb=Informática > Componentes para PC > SSD", log
        )
        self.assertIn("original_category=SSD", log)
        self.assertIn(
            "detector_function=Notifier.detect_mercado_livre_category", log
        )
        self.assertIn(
            "applied_rule=MERCADO_LIVRE_BREADCRUMB_KEYWORDS", log
        )
        self.assertIn("rejection_reason=", log)
        self.assertNotIn("<html", log.casefold())

    def test_fluxo_reconsulta_somente_ml_quando_taxonomia_esta_ausente(self):
        source = Path(
            "src/ui/affiliate_links_page.py"
        ).read_text(encoding="utf-8")
        self.assertIn("mercado_livre_category_enrichment", source)
        self.assertIn('store_key == "mercado livre"', source)
        self.assertIn(
            "or mercado_livre_category_enrichment", source
        )


if __name__ == "__main__":
    unittest.main()
