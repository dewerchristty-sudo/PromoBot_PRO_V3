from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from src.database.offer_pipeline_repository import OfferPipelineRepository
from src.offers.models import PriceObservation
from src.offers.price_history_dashboard import PriceHistoryDashboard


class OfferPipelineRepositoryTest(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "pipeline.db"
        self.repository = OfferPipelineRepository(self.path)
        self.repository.migrate()
        self.now = datetime(2026, 7, 26, 12, tzinfo=timezone.utc)

    def tearDown(self):
        self.repository.close()
        self.tempdir.cleanup()

    def test_migracao_cria_tabelas_sem_tabelas_legadas(self):
        self.repository.migrate()
        self.assertTrue({
            "offer_price_observations",
            "offer_price_history",
            "offer_pipeline_runs",
            "offer_pipeline_items",
        }.issubset(self.repository.table_names()))
        self.assertNotIn("produtos", self.repository.table_names())
        self.assertNotIn("alertas", self.repository.table_names())

    def test_historico_persistente_ignora_valor_invalido(self):
        self.assertTrue(self.repository.add(PriceObservation(
            "identity", 100, self.now, "Amazon"
        )))
        self.assertFalse(self.repository.add(PriceObservation(
            "identity", 0, self.now, "Amazon"
        )))
        restored = OfferPipelineRepository(self.path)
        restored.migrate()
        values = restored.list_for(
            "identity",
            self.now - timedelta(days=1),
        )
        restored.close()
        self.assertEqual([item.price for item in values], [100])

    def test_historico_persiste_metadados_e_deduplica_dia_preco(self):
        observation = PriceObservation(
            "identity", 199.9, self.now, "coleta",
            store="Amazon", title="SSD 1TB", currency="BRL",
            original_url="https://example.com/p",
            image_url="https://example.com/i.jpg",
            availability="em estoque",
        )
        self.assertTrue(self.repository.add(observation))
        self.assertFalse(self.repository.add(PriceObservation(
            "identity", 199.9, self.now + timedelta(hours=1), "coleta",
            store="Amazon", title="SSD 1TB", currency="BRL",
            original_url="https://example.com/p",
            image_url="https://example.com/i.jpg",
            availability="em estoque",
        )))
        restored = self.repository.list_for("identity")
        self.assertEqual(restored[0].store, "Amazon")
        self.assertEqual(restored[0].title, "SSD 1TB")
        self.assertEqual(restored[0].availability, "em estoque")

    def test_indices_do_pipeline_sao_criados(self):
        expected = {
            "idx_offer_observations_identity_time",
            "idx_offer_pipeline_runs_created",
            "idx_offer_pipeline_items_run",
            "idx_offer_pipeline_items_identity",
            "idx_offer_pipeline_items_score",
            "idx_offer_pipeline_items_queue_status",
            "idx_price_history_identity_time",
            "idx_price_history_store_time",
            "idx_price_history_date",
        }
        self.assertTrue(expected.issubset(self.repository.index_names()))

    def test_indicadores_preparados_sem_alterar_dashboard_existente(self):
        for days, price in ((2, 100), (1, 90), (0, 80)):
            self.repository.add(PriceObservation(
                "identity", price, self.now - timedelta(days=days),
                "coleta", store="Amazon", title="SSD 1TB"
            ))
        snapshot = PriceHistoryDashboard(self.repository).snapshot()
        self.assertEqual(snapshot["products_monitored"], 1)
        self.assertEqual(snapshot["history_days"], 2)
        self.assertEqual(snapshot["lowest_price"], 80)
        self.assertEqual(snapshot["highest_price"], 100)
        self.assertEqual(snapshot["products_falling"], 1)
        self.assertEqual(snapshot["new_records"], 1)


if __name__ == "__main__":
    unittest.main()
