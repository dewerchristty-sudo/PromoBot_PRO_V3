from pathlib import Path
import tempfile
import unittest

from src.affiliates.config import AffiliateConfig, StoreAffiliateConfig
from src.affiliates.manager import AffiliateManager
from src.offers.filters import OfferFilter
from src.offers.models import OfferCandidate
from src.offers.readiness import OfferReadinessEnricher


class OfferReadinessTest(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.managers = []
        self.enricher = self.make_enricher()

    def tearDown(self):
        for manager in self.managers:
            manager.close()
        self.tempdir.cleanup()

    def make_enricher(self, *, amazon=None, mercado=None, shopee=None):
        config = AffiliateConfig(
            mercado_livre=mercado or StoreAffiliateConfig(),
            amazon=amazon or StoreAffiliateConfig(),
            shopee=shopee or StoreAffiliateConfig(),
            cache_path=Path(self.tempdir.name) / (
                f"affiliate-{len(self.managers)}.db"
            ),
            cache_ttl_hours=24,
        )
        manager = AffiliateManager(config)
        self.managers.append(manager)
        return OfferReadinessEnricher(manager)

    def product(self, store="Amazon", **changes):
        value = {
            "loja": store, "titulo": "SSD Kingston NV3 1TB",
            "preco": "999,90", "preco_antigo": "1.199,90",
            "link": {
                "Amazon": "https://www.amazon.com.br/dp/B012345678",
                "Mercado Livre":
                    "https://produto.mercadolivre.com.br/MLB-123456",
                "Shopee": "https://shopee.com.br/produto-i.1.2",
            }[store],
            "imagem": "https://images.example.com/produto.webp",
        }
        value.update(changes)
        return value

    def test_preserva_link_original_e_afiliado_oficial_fornecido(self):
        enricher = self.make_enricher(amazon=StoreAffiliateConfig(
            associate_tag="achadinhos-20"
        ))
        result = enricher.prepare(self.product(
            affiliate_link=(
                "https://www.amazon.com.br/dp/B012345678"
                "?tag=achadinhos-20"
            )
        ))
        self.assertEqual(
            result.product["original_url"],
            "https://www.amazon.com.br/dp/B012345678",
        )
        self.assertEqual(result.product["affiliate_status"], "PROVIDED")
        candidate = OfferCandidate.from_mapping(result.product)
        self.assertNotIn(
            "link_afiliado_ausente",
            OfferFilter().analyze(candidate).operational_blocks,
        )

    def test_marketplace_sem_integracao_oficial_fica_not_configured(self):
        result = self.enricher.prepare(self.product("Mercado Livre"))
        self.assertEqual(result.product["affiliate_status"], "NOT_CONFIGURED")
        self.assertEqual(result.product["affiliate_url"], "")
        self.assertTrue(result.product["original_url"])

    def test_usa_apenas_link_oficial_mapeado_quando_configurado(self):
        link = "https://produto.mercadolivre.com.br/MLB-123456"
        enricher = self.make_enricher(mercado=StoreAffiliateConfig(
            mapping="MLB123456=https://meli.la/oficial"
        ))
        result = enricher.prepare(
            self.product("Mercado Livre", link=link)
        )
        self.assertEqual(
            result.product["affiliate_url"], "https://meli.la/oficial"
        )
        self.assertEqual(result.product["affiliate_status"], "GENERATED")

    def test_nao_inventa_identificador_de_afiliado(self):
        enricher = self.make_enricher(shopee=StoreAffiliateConfig(
            affiliate_id="123"
        ))
        result = enricher.prepare(self.product("Shopee"))
        self.assertEqual(result.product["affiliate_url"], "")

    def test_imagem_lazy_srcset_jsonld_e_open_graph(self):
        cases = (
            ("data-src", "https://img.example/a.webp"),
            ("srcset", "https://img.example/b.webp 2x"),
            ("data-srcset", "https://img.example/c.webp 1x"),
            ("json_ld_image", "https://img.example/d.webp"),
            ("og_image", "https://img.example/e.webp"),
        )
        for field, expected in cases:
            value = self.product(imagem="", **{field: expected})
            with self.subTest(field=field):
                result = self.enricher.prepare(value)
                self.assertTrue(result.product["image_url"].startswith(
                    expected.split()[0]
                ))

    def test_normaliza_preco_e_calcula_desconto_real(self):
        result = self.enricher.prepare(self.product())
        self.assertEqual(result.product["current_price"], 999.9)
        self.assertEqual(result.product["previous_price"], 1199.9)
        self.assertAlmostEqual(result.product["discount_percent"], 16.668, 2)
        self.assertEqual(
            result.product["discount_source"],
            "preco_anterior_anunciado",
        )

    def test_sem_preco_anterior_nao_inventa_desconto(self):
        result = self.enricher.prepare(
            self.product(preco_antigo="")
        )
        self.assertEqual(result.product["previous_price"], 0)
        self.assertEqual(result.product["discount_percent"], 0)
        self.assertEqual(result.product["discount_source"], "indisponivel")

    def test_score_analitico_independe_de_link_afiliado(self):
        from src.offers.score import OfferScore
        base = self.enricher.prepare(self.product("Mercado Livre")).product
        candidate = OfferCandidate.from_mapping(base)
        score_without = OfferScore().calculate(candidate).total
        candidate.affiliate_link = "https://meli.la/oficial"
        score_with = OfferScore().calculate(candidate).total
        self.assertEqual(score_without, score_with)
        self.assertIn(
            "link_afiliado_ausente",
            OfferFilter().analyze(
                OfferCandidate.from_mapping(base)
            ).operational_blocks,
        )


if __name__ == "__main__":
    unittest.main()
