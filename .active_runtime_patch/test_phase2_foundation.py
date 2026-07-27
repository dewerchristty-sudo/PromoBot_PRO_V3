import importlib
import sys
import unittest
from datetime import datetime, timedelta

from src.phase2 import ApprovalDecision, OfferSnapshot, Phase2Foundation
from src.phase2.models import PriceMovement, PriceObservation, PublicationPlan


class Phase2FoundationTest(unittest.TestCase):
    def setUp(self):
        self.offer = OfferSnapshot(
            product_key="test-1",
            store="Teste",
            title="Produto",
            current_price=80.0,
            previous_price=100.0,
            url="https://example.test/product",
            category="Casa",
            group="Revisão",
        )

    def test_fundacao_nao_e_importada_pelo_runtime_atual(self):
        sys.modules.pop("src.phase2", None)
        importlib.reload(importlib.import_module("src.app"))
        self.assertNotIn("src.phase2", sys.modules)

    def test_fila_planeja_sem_publicar(self):
        foundation = Phase2Foundation()
        plan = PublicationPlan(
            "plan-1",
            self.offer,
            datetime.now() - timedelta(minutes=1),
            "destino-configurado",
        )
        foundation.publication_queue.add(plan)
        self.assertEqual(foundation.publication_queue.due(), [plan])
        self.assertFalse(hasattr(foundation.publication_queue, "publish"))
        foundation.publication_queue.pause("plan-1")
        self.assertEqual(foundation.publication_queue.due(), [])
        foundation.publication_queue.resume("plan-1")
        self.assertEqual(len(foundation.publication_queue.due()), 1)

    def test_historico_e_somente_observacional(self):
        foundation = Phase2Foundation()
        foundation.history.record(self.offer)
        self.assertTrue(foundation.history.product_seen("test-1"))
        self.assertTrue(foundation.history.link_seen(self.offer.url))
        self.assertFalse(hasattr(foundation.history, "block"))

    def test_dashboard_agrega_sem_banco(self):
        snapshot = Phase2Foundation().statistics.build(
            [self.offer],
            {"test-1": ApprovalDecision.APPROVED},
        )
        self.assertEqual(snapshot.products, 1)
        self.assertEqual(snapshot.approved, 1)
        self.assertEqual(snapshot.by_store, {"Teste": 1})
        self.assertAlmostEqual(snapshot.average_discount, 20.0)

    def test_aprovacao_em_lote_nao_envia(self):
        workspace = Phase2Foundation().approvals
        batch = workspace.create("batch-1", ["test-1", "test-2", "test-1"])
        changed = workspace.decide(
            batch,
            "test-1",
            ApprovalDecision.APPROVED,
        )
        self.assertEqual(changed.decisions["test-1"], ApprovalDecision.APPROVED)
        self.assertFalse(hasattr(workspace, "send"))

    def test_lojas_futuras_ficam_desativadas(self):
        catalog = Phase2Foundation().stores
        self.assertEqual(
            {item.key for item in catalog.all()},
            {"magalu", "kabum", "pichau", "terabyte", "aliexpress"},
        )
        self.assertTrue(all(not item.enabled for item in catalog.all()))

    def test_monitor_apenas_analisa_variacao(self):
        now = datetime.now()
        previous = PriceObservation("test-1", "Teste", 100.0, now)
        current = PriceObservation(
            "test-1",
            "Teste",
            80.0,
            now + timedelta(hours=1),
        )
        result = Phase2Foundation().price_analyzer.analyze(
            current,
            [previous],
        )
        self.assertEqual(result.movement, PriceMovement.DECREASED)
        self.assertEqual(result.absolute_change, -20.0)
        self.assertEqual(result.percentage_change, -20.0)


if __name__ == "__main__":
    unittest.main()
