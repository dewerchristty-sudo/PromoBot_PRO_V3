from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from src.affiliates.cache import AffiliateCache
from src.affiliates.config import AffiliateConfig, StoreAffiliateConfig
from src.affiliates.manager import AffiliateManager


class AffiliateManagerTest(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "affiliate.db"
        self.resources = []

    def tearDown(self):
        for manager in self.resources:
            manager.close()
        self.tempdir.cleanup()

    def manager(self, *, amazon=None, mercado=None, shopee=None, cache=None):
        config = AffiliateConfig(
            mercado_livre=mercado or StoreAffiliateConfig(),
            amazon=amazon or StoreAffiliateConfig(),
            shopee=shopee or StoreAffiliateConfig(),
            cache_path=self.path,
            cache_ttl_hours=24,
        )
        value = AffiliateManager(config, cache=cache)
        self.resources.append(value)
        return value

    def test_amazon_usa_associate_tag_oficial(self):
        manager = self.manager(amazon=StoreAffiliateConfig(
            associate_tag="achadinhos-20"
        ))
        result = manager.resolve(
            "Amazon", "https://www.amazon.com.br/dp/B012345678?ref=x"
        )
        self.assertEqual(result.status, "GENERATED")
        self.assertIn("tag=achadinhos-20", result.affiliate_url)
        self.assertEqual(result.source, "associate_tag")

    def test_mercado_livre_usa_mapa_oficial(self):
        manager = self.manager(mercado=StoreAffiliateConfig(
            mapping="MLB123456=https://meli.la/oficial"
        ))
        result = manager.resolve(
            "Mercado Livre",
            "https://produto.mercadolivre.com.br/MLB-123456",
        )
        self.assertEqual(result.status, "GENERATED")
        self.assertEqual(result.affiliate_url, "https://meli.la/oficial")

    def test_shopee_possui_integracao_estruturada_por_template(self):
        manager = self.manager(shopee=StoreAffiliateConfig(
            affiliate_id="vivi",
            template="https://s.shopee.com.br/{affiliate_id}?url={url}",
        ))
        result = manager.resolve(
            "Shopee", "https://shopee.com.br/produto-i.123.456"
        )
        self.assertEqual(result.status, "GENERATED")
        self.assertIn("vivi", result.affiliate_url)

    def test_sem_configuracao_falha_sem_interromper(self):
        result = self.manager().resolve(
            "Amazon", "https://www.amazon.com.br/dp/B012345678"
        )
        self.assertEqual(result.status, "NOT_CONFIGURED")
        self.assertFalse(result.valid)

    def test_dominio_invalido_e_bloqueado(self):
        result = self.manager().resolve(
            "Amazon", "https://example.com/produto"
        )
        self.assertEqual(result.status, "INVALID")
        self.assertEqual(result.error, "url_original_invalida_para_loja")

    def test_cache_reutiliza_link_sem_regenerar(self):
        manager = self.manager(amazon=StoreAffiliateConfig(
            associate_tag="achadinhos-20"
        ))
        url = "https://www.amazon.com.br/dp/B012345678"
        first = manager.resolve("Amazon", url)
        second = manager.resolve("Amazon", url)
        self.assertEqual(first.status, "GENERATED")
        self.assertEqual(second.status, "CACHED")
        self.assertTrue(second.cache_hit)
        metrics = manager.metrics()
        self.assertEqual(metrics.generated, 1)
        self.assertEqual(metrics.cache_hits, 1)

    def test_cache_expira_no_ttl(self):
        now = [datetime(2026, 7, 26, tzinfo=timezone.utc)]
        cache = AffiliateCache(
            self.path, ttl_hours=1, clock=lambda: now[0]
        )
        manager = self.manager(
            amazon=StoreAffiliateConfig(associate_tag="achadinhos-20"),
            cache=cache,
        )
        url = "https://www.amazon.com.br/dp/B012345678"
        manager.resolve("Amazon", url)
        now[0] += timedelta(hours=2)
        self.assertEqual(manager.resolve("Amazon", url).status, "GENERATED")

    def test_link_amazon_fornecido_exige_tag(self):
        manager = self.manager(amazon=StoreAffiliateConfig(
            associate_tag="achadinhos-20"
        ))
        result = manager.resolve(
            "Amazon",
            "https://www.amazon.com.br/dp/B012345678",
            "https://www.amazon.com.br/dp/B012345678?ref=sem-tag",
        )
        self.assertEqual(result.status, "INVALID")


if __name__ == "__main__":
    unittest.main()
