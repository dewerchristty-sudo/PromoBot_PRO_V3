from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.affiliates.amazon import AmazonAffiliateProvider
from src.affiliates.cache import AffiliateCache
from src.affiliates.config import AffiliateConfig, StoreAffiliateConfig
from src.affiliates.diagnostics import (
    AffiliateDiagnostics, mercado_livre_session_status,
    write_validation_reports,
)
from src.affiliates.manager import AffiliateManager
from src.affiliates.validation import (
    is_placeholder, mask_secret, safe_absolute_url,
    validate_store_config,
)
from scripts.setup_affiliates import main as setup_main


class AffiliateValidationTest(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self):
        self.tempdir.cleanup()

    def config(self, amazon=None, mercado=None, shopee=None):
        return AffiliateConfig(
            mercado_livre=mercado or StoreAffiliateConfig(),
            amazon=amazon or StoreAffiliateConfig(),
            shopee=shopee or StoreAffiliateConfig(),
            cache_path=self.root / "cache.db",
            cache_ttl_hours=24,
        )

    def test_configuracao_ausente_e_parcial(self):
        provider = AmazonAffiliateProvider(StoreAffiliateConfig())
        absent = validate_store_config(
            "Amazon", StoreAffiliateConfig(), provider
        )
        partial = validate_store_config(
            "Amazon", StoreAffiliateConfig(affiliate_id="real-id"), provider
        )
        self.assertEqual(absent.status, "NOT_CONFIGURED")
        self.assertEqual(partial.status, "PARTIALLY_CONFIGURED")

    def test_configuracao_valida(self):
        config = StoreAffiliateConfig(associate_tag="lojavivi-20")
        result = validate_store_config(
            "Amazon", config, AmazonAffiliateProvider(config)
        )
        self.assertEqual(result.status, "CONFIGURED")
        self.assertTrue(result.generation_available)

    def test_placeholders_padrao_e_configuravel(self):
        self.assertTrue(is_placeholder("sua_tag"))
        with patch.dict("os.environ", {
            "AFFILIATE_PLACEHOLDER_VALUES": "nao_usar"
        }):
            self.assertTrue(is_placeholder("nao_usar"))

    def test_segredo_e_mascarado(self):
        masked = mask_secret("segredo-super-longo")
        self.assertNotIn("segredo-super-longo", masked)
        self.assertTrue(masked.startswith("se"))
        self.assertTrue(masked.endswith("go"))

    def test_url_insegura_e_loja_incorreta_sao_rejeitadas(self):
        domains = ("amazon.com.br",)
        self.assertFalse(safe_absolute_url(
            "javascript:alert(1)", domains
        ))
        self.assertFalse(safe_absolute_url(
            "http://www.amazon.com.br/dp/B012345678", domains
        ))
        self.assertFalse(safe_absolute_url(
            "https://shopee.com.br/produto", domains
        ))

    def test_link_de_outro_produto_e_rejeitado(self):
        config = StoreAffiliateConfig(associate_tag="lojavivi-20")
        provider = AmazonAffiliateProvider(config)
        self.assertFalse(provider.validate(
            "https://www.amazon.com.br/dp/B099999999?tag=lojavivi-20",
            "https://www.amazon.com.br/dp/B012345678",
        ))

    def test_falha_de_uma_loja_nao_impede_outra(self):
        config = self.config(
            amazon=StoreAffiliateConfig(associate_tag="lojavivi-20")
        )
        manager = AffiliateManager(config)
        try:
            failed = manager.resolve(
                "Shopee", "https://shopee.com.br/produto-i.1.2"
            )
            success = manager.resolve(
                "Amazon", "https://www.amazon.com.br/dp/B012345678"
            )
        finally:
            manager.close()
        self.assertFalse(failed.valid)
        self.assertTrue(success.valid)

    def test_sessao_mercado_livre_exigindo_verificacao(self):
        diagnostic = self.root / "diagnostic.txt"
        diagnostic.write_text(
            "final_url=https://mercadolivre.com.br/gz/account-verification",
            encoding="utf-8",
        )
        self.assertEqual(
            mercado_livre_session_status(
                self.root / "profile", diagnostic
            ),
            "VERIFICATION_REQUIRED",
        )

    def test_shopee_sem_metodo_exige_configuracao_manual(self):
        config = StoreAffiliateConfig()
        from src.affiliates.shopee import ShopeeAffiliateProvider
        result = validate_store_config(
            "Shopee", config, ShopeeAffiliateProvider(config)
        )
        self.assertEqual(
            result.status, "MANUAL_CONFIGURATION_REQUIRED"
        )

    def test_diagnostico_e_relatorios_nao_vazam_segredo(self):
        secret = "lojavivi-segreda-20"
        config = self.config(
            amazon=StoreAffiliateConfig(associate_tag=secret)
        )
        manager = AffiliateManager(config)
        diagnostic = AffiliateDiagnostics(config, manager)
        try:
            report = diagnostic.run()
            paths = write_validation_reports(report, self.root / "reports")
        finally:
            manager.close()
        combined = "\n".join(
            path.read_text(encoding="utf-8-sig") for path in paths
        )
        self.assertNotIn(secret, combined)
        amazon = next(
            row for row in report["stores"] if row["store"] == "Amazon"
        )
        self.assertEqual(amazon["status"], "VALIDATED")

    @patch("scripts.setup_affiliates.AffiliateDiagnostics")
    def test_assistente_nao_altera_env_sem_confirmacao(self, diagnostic_cls):
        diagnostic_cls.return_value.run.return_value = {
            "stores": [{
                "store": name, "status": "NOT_CONFIGURED",
                "reason": "ausente", "masked_values": {}, "missing": (),
            } for name in ("Mercado Livre", "Amazon", "Shopee")]
        }
        env = self.root / ".env"
        env.write_text("SEGREDO=preservado\n", encoding="utf-8")
        before = env.read_bytes()
        with patch("scripts.setup_affiliates.Path", wraps=Path):
            setup_main(input_fn=lambda _prompt: "")
        self.assertEqual(env.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
