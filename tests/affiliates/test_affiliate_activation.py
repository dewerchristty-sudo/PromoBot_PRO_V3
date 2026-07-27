import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.activate_affiliates import build_onboarding, write_onboarding
from scripts.prepare_shopee_affiliate_mapping import (
    build_candidates, write_candidates,
)
from scripts.recover_mercado_livre_session import classify_session, main as recover
from scripts.run_offer_dry_run import normalize_store_argument
from src.affiliates.config import AffiliateConfig, StoreAffiliateConfig


class AffiliateActivationTest(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self):
        self.tempdir.cleanup()

    def config(self, shopee=None):
        return AffiliateConfig(
            mercado_livre=StoreAffiliateConfig(),
            amazon=StoreAffiliateConfig(),
            shopee=shopee or StoreAffiliateConfig(),
            cache_path=self.root / "cache.db",
            cache_ttl_hours=24,
        )

    def test_diagnostico_de_sessao(self):
        self.assertEqual(classify_session(
            "https://mercadolivre.com.br/gz/account-verification"
        ), "VERIFICATION_REQUIRED")
        self.assertEqual(classify_session(
            "https://www.mercadolivre.com.br/"
        ), "SESSION_READY")
        self.assertEqual(classify_session(
            "https://www.mercadolivre.com.br/login"
        ), "LOGIN_REQUIRED")

    def test_recuperacao_manual_sem_pause(self):
        source = Path(
            "scripts/recover_mercado_livre_session.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("page.pause(", source)
        self.assertNotIn("devtools", source.casefold())
        self.assertNotIn("PWDEBUG=", source)

    def test_shopee_produto_mapeado_e_sem_mapa(self):
        mapped_url = "https://shopee.com.br/produto-i.10.20"
        missing_url = "https://shopee.com.br/outro-i.30.40"
        config = self.config(StoreAffiliateConfig(
            mapping="10.20=https://s.shopee.com.br/link-real"
        ))
        candidates = build_candidates([
            {"identidade": "a", "titulo": "Mapeado",
             "original_url": mapped_url},
            {"identidade": "b", "titulo": "Sem mapa",
             "original_url": missing_url},
        ], config)
        self.assertEqual(
            [row["mapping_status"] for row in candidates],
            ["MAPPED", "MISSING"],
        )
        self.assertEqual(candidates[1]["affiliate_url"], "")

    def test_arquivo_de_candidatos_nao_inventa_links(self):
        candidates = [{
            "canonical_identity": "abc", "title": "Produto",
            "original_url": "https://shopee.com.br/produto-i.1.2",
            "mapping_status": "MISSING", "affiliate_url": "",
            "instruction": "Preencha manualmente.",
        }]
        path = write_candidates(candidates, self.root / "candidates.json")
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["products"][0]["affiliate_url"], "")
        self.assertIn("nao altera o .env", payload["warning"])

    def test_dry_run_aceita_filtro_por_loja(self):
        self.assertEqual(
            normalize_store_argument("mercado_livre"), "mercado_livre"
        )
        self.assertEqual(normalize_store_argument("amazon"), "amazon")
        self.assertEqual(normalize_store_argument("shopee"), "shopee")

    def test_onboarding_isola_falhas_e_nao_contem_segredos(self):
        diagnostic = {"stores": [
            {"store": "Mercado Livre", "status": "VALIDATED",
             "session_status": "VERIFICATION_REQUIRED"},
            {"store": "Amazon", "status": "NOT_CONFIGURED",
             "session_status": ""},
            {"store": "Shopee", "status": "VALIDATED",
             "session_status": ""},
        ]}
        dry = {
            "stores": {
                "Amazon": {"collected": 1, "error": ""},
                "Shopee": {"collected": 1, "error": ""},
            },
            "affiliate_by_store": {
                "Amazon": {"failures": 1},
                "Shopee": {"failures": 1},
            },
        }
        candidates = [{
            "mapping_status": "MISSING", "affiliate_url": "",
        }]
        report = build_onboarding(diagnostic, dry, candidates)
        paths = write_onboarding(report, self.root / "onboarding")
        text = "\n".join(
            path.read_text(encoding="utf-8-sig") for path in paths
        )
        self.assertNotIn("amazon-segredo-20", text)
        self.assertEqual(len(report["stores"]), 3)


if __name__ == "__main__":
    unittest.main()
