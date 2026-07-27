from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from src.database.offer_pipeline_repository import OfferPipelineRepository


class OfferCanaryRepositoryTest(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.repository = OfferPipelineRepository(
            Path(self.tempdir.name) / "canary.db"
        )
        self.repository.migrate()

    def tearDown(self):
        self.repository.close()
        self.tempdir.cleanup()

    def row(self, identity="identidade-1", scheduler="inteligente"):
        return {
            "audit_id": f"audit-{identity}",
            "identity": identity,
            "title": "Produto",
            "store": "Amazon",
            "category": "Tecnologia",
            "score": 95,
            "scheduler": scheduler,
            "legacy_decision": "enviar",
            "intelligent_decision": "enviar",
            "difference": "nao",
            "reason": "aprovado",
            "flags_json": "{}",
            "canary_percent": 10,
            "result": "Enviado por: WhatsApp",
            "sent": True,
            "rollback_reason": "",
            "decision_ms": 1.5,
            "created_at": datetime.now(timezone.utc),
        }

    def test_migracao_auditoria_metricas_e_duplicidade_persistente(self):
        self.assertIn(
            "offer_canary_decisions", self.repository.table_names()
        )
        self.repository.record_canary_decisions([self.row()])
        self.assertTrue(
            self.repository.canary_identity_was_sent("identidade-1")
        )
        metrics = self.repository.canary_metrics()
        self.assertEqual(metrics["intelligent_sends"], 1)
        self.assertEqual(metrics["comparisons"], 1)
        with self.assertRaises(Exception):
            other = self.row("identidade-1")
            other["audit_id"] = "outro-audit"
            self.repository.record_canary_decisions([other])


if __name__ == "__main__":
    unittest.main()
