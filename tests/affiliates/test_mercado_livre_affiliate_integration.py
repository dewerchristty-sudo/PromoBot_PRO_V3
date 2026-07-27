from pathlib import Path
import tempfile
import unittest

from scripts.validate_mercado_livre_affiliate_integration import (
    validate_real_integration,
)
from scripts.add_mercado_livre_affiliate_mapping import add_mapping
from src.affiliates.config import (
    AffiliateConfig, DEFAULT_ENV_PATH, StoreAffiliateConfig,
)
from src.affiliates.diagnostics import AffiliateDiagnostics
from src.affiliates.manager import AffiliateManager


class MercadoLivreAffiliateIntegrationTest(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self):
        self.tempdir.cleanup()

    def config(self, mapping="", template=""):
        return AffiliateConfig(
            mercado_livre=StoreAffiliateConfig(
                mapping=mapping, template=template,
            ),
            amazon=StoreAffiliateConfig(),
            shopee=StoreAffiliateConfig(),
            cache_path=self.root / "cache.db",
            cache_ttl_hours=24,
            env_path=DEFAULT_ENV_PATH,
            env_file_found=DEFAULT_ENV_PATH.is_file(),
        )

    def test_env_e_resolvido_pela_raiz_do_projeto(self):
        config = AffiliateConfig.from_environment()
        self.assertEqual(config.env_path, DEFAULT_ENV_PATH.resolve())
        self.assertEqual(config.env_file_found, DEFAULT_ENV_PATH.is_file())

    def test_mapa_especifico_nao_e_declarado_validado_globalmente(self):
        config = self.config(
            "MLB987654321=https://meli.la/link-oficial"
        )
        manager = AffiliateManager(config)
        diagnostic = AffiliateDiagnostics(config, manager)
        try:
            report = diagnostic.run()
        finally:
            manager.close()
        mercado = report["stores"][0]
        self.assertEqual(mercado["status"], "CONFIGURED")
        self.assertFalse(mercado["validated"])
        self.assertEqual(
            mercado["config_audit"]["manager_status"],
            "AVAILABLE_FOR_MAPPED_PRODUCTS",
        )

    def test_fluxo_local_com_produto_real_mapeado_fica_pronto(self):
        config = self.config(
            "MLB987654321=https://meli.la/link-oficial"
        )
        report = validate_real_integration(config, [{
            "loja": "Mercado Livre",
            "titulo": "SSD NVMe Kingston 1TB Modelo NV3",
            "preco": "399,90",
            "link":
                "https://produto.mercadolivre.com.br/MLB-987654321",
            "imagem": "https://http2.mlstatic.com/D_NQ_NP_produto.webp",
        }])
        self.assertEqual(report["status"], "PASSED")
        self.assertEqual(report["links_generated"], 1)
        self.assertEqual(report["operationally_ready"], 1)
        self.assertEqual(
            report["products"][0]["affiliate_url"],
            "[oficial_e_mascarado]",
        )

    def test_produto_fora_do_mapa_falha_claramente(self):
        config = self.config(
            "MLB987654321=https://meli.la/link-oficial"
        )
        report = validate_real_integration(config, [{
            "loja": "Mercado Livre", "titulo": "Produto diferente",
            "preco": "100,00",
            "link":
                "https://produto.mercadolivre.com.br/MLB-111111111",
            "imagem": "https://http2.mlstatic.com/produto.webp",
        }])
        self.assertEqual(
            report["status"], "FAILED_NO_REAL_PRODUCT_COVERAGE"
        )
        self.assertEqual(report["links_generated"], 0)
        self.assertTrue(report["manual_action"])

    def test_adiciona_entrada_preservando_mapa_e_cria_backup(self):
        env = self.root / ".env"
        env.write_text(
            "OUTRA_VARIAVEL=preservada\n"
            "MERCADOLIVRE_AFFILIATE_MAP="
            "MLB111111111=https://meli.la/link-anterior\n",
            encoding="utf-8",
        )
        result = add_mapping(
            "https://www.mercadolivre.com.br/produto/p/MLB50957106",
            "https://meli.la/link-novo",
            env,
        )
        content = env.read_text(encoding="utf-8")
        self.assertIn("OUTRA_VARIAVEL=preservada", content)
        self.assertIn("MLB111111111=", content)
        self.assertIn("MLB50957106=", content)
        self.assertTrue(result["backup"].is_file())


if __name__ == "__main__":
    unittest.main()
