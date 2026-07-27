from datetime import datetime, timedelta, timezone
import unittest

from src.offers import (
    DuplicateChecker,
    OfferAnalysisPolicy,
    OfferCandidate,
    OfferIdentity,
)


class DuplicateCheckerTest(unittest.TestCase):

    def setUp(self):
        self.now = datetime(2026, 7, 26, 12, tzinfo=timezone.utc)
        self.policy = OfferAnalysisPolicy(
            duplicate_window_hours=24,
            significant_price_drop_percent=5,
        )
        self.checker = DuplicateChecker(policy=self.policy)
        self.identity_service = OfferIdentity()

    def identity(self, title="SSD Kingston NV3 1TB", link=""):
        return self.identity_service.identify(OfferCandidate(
            title=title,
            product_link=link,
            current_price=100,
        ))

    def test_mesmo_link_dentro_de_vinte_e_quatro_horas(self):
        identity = self.identity(link="https://example.com/item/1")
        self.checker.remember(identity, 100, self.now - timedelta(hours=1))
        result = self.checker.check(identity, 100, self.now)
        self.assertTrue(result.is_duplicate)
        self.assertEqual(result.duplicate_type, "mesmo_link")

    def test_mesmo_produto_com_link_diferente(self):
        first = self.identity(link="https://example.com/item/1")
        second = self.identity(link="https://example.com/item/2")
        self.checker.remember(first, 100, self.now - timedelta(hours=1))
        result = self.checker.check(second, 100, self.now)
        self.assertTrue(result.is_duplicate)
        self.assertEqual(result.duplicate_type, "mesma_promocao")

    def test_produto_fora_da_janela_nao_e_duplicado(self):
        identity = self.identity()
        self.checker.remember(identity, 100, self.now - timedelta(hours=25))
        result = self.checker.check(identity, 100, self.now)
        self.assertFalse(result.is_duplicate)

    def test_queda_superior_a_cinco_porcento_pode_ser_aceita(self):
        identity = self.identity()
        self.checker.remember(identity, 100, self.now - timedelta(hours=1))
        result = self.checker.check(identity, 94, self.now)
        self.assertFalse(result.is_duplicate)
        self.assertEqual(result.duplicate_type, "nova_promocao")

    def test_queda_inferior_a_cinco_porcento_continua_duplicada(self):
        identity = self.identity()
        self.checker.remember(identity, 100, self.now - timedelta(hours=1))
        result = self.checker.check(identity, 96, self.now)
        self.assertTrue(result.is_duplicate)
        self.assertTrue(result.reasons)

    def test_blocked_until_e_calculado_corretamente(self):
        identity = self.identity()
        occurred_at = self.now - timedelta(hours=2)
        self.checker.remember(identity, 100, occurred_at)
        result = self.checker.check(identity, 100, self.now)
        self.assertEqual(
            result.blocked_until,
            occurred_at + timedelta(hours=24),
        )
        self.assertTrue(result.shadow_mode)
        self.assertFalse(result.blocks_current_flow)


if __name__ == "__main__":
    unittest.main()
