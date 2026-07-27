from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import tempfile
import time
import unittest

from src.database.offer_pipeline_repository import OfferPipelineRepository
from src.offers.models import QueueOffer
from src.offers.statistics import (
    OfferDashboardFilter,
    OfferStatistics,
)


class OfferStatisticsTest(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "dashboard.db"
        self.repository = OfferPipelineRepository(self.path)
        self.repository.migrate()
        self.statistics = OfferStatistics(self.repository)
        self.now = datetime(2026, 7, 26, 12, tzinfo=timezone.utc)
        self.seed()

    def tearDown(self):
        self.repository.close()
        self.tempdir.cleanup()

    def queue_offer(self, index, status, score, store, category):
        item, _ = self.repository.enqueue(QueueOffer(
            id=None,
            evaluation_id=f"eval-{index}",
            product_id=str(index),
            canonical_identity=f"identity-{index}",
            promotion_signature=f"promotion-{index}",
            title=f"Produto {index}",
            store=store,
            category=category,
            current_price=100 + index,
            previous_price=150 + index,
            discount_percent=30,
            saving_amount=50,
            score=score,
            classification=(
                "oferta_excelente" if score >= 90
                else "boa_oferta" if score >= 70
                else "oferta_fraca"
            ),
            confidence=6,
            score_components={"discount": 25},
            status=status,
            priority=score,
            available_at=self.now,
            expires_at=self.now + timedelta(hours=12),
            created_at=self.now,
            blocked_reason="imagem_ausente" if status == "blocked" else "",
        ))
        return item

    def seed(self):
        self.repository.conn.execute("""
            INSERT INTO offer_pipeline_runs(run_id, created_at)
            VALUES('run-dashboard', ?)
        """, (self.repository.iso(self.now),))
        self.repository.conn.commit()
        data = (
            (1, "selected_shadow", 95, "Amazon", "Tecnologia", 1, "", "selected_shadow"),
            (2, "blocked", 80, "Shopee", "Casa", 1, "mesmo_produto", "bloqueado"),
            (3, "discarded", 30, "Amazon", "Tecnologia", 0, "", "score_insuficiente"),
        )
        for index, status, score, store, category, approved, duplicate, scheduler in data:
            queue = self.queue_offer(
                index, status, score, store, category
            )
            diagnostic = {
                "canonical_identity": f"identity-{index}",
                "score": score,
                "reason": scheduler,
            }
            self.repository.conn.execute("""
                INSERT INTO offer_pipeline_items(
                    run_id, product_id, canonical_identity,
                    promotion_signature, title, store, score,
                    classification, filter_approved, duplicate_type,
                    queue_item_id, queue_status, scheduler_status,
                    diagnostic_json, processing_ms, created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                "run-dashboard",
                str(index),
                f"identity-{index}",
                f"promotion-{index}",
                f"Produto {index}",
                store,
                score,
                (
                    "oferta_excelente" if score >= 90
                    else "boa_oferta" if score >= 70
                    else "oferta_fraca"
                ),
                approved,
                duplicate,
                queue.id,
                status,
                scheduler,
                json.dumps(diagnostic),
                index * 2.5,
                self.repository.iso(self.now + timedelta(minutes=index)),
            ))
            for offset, price in enumerate((150 + index, 100 + index)):
                self.repository.conn.execute("""
                    INSERT INTO offer_price_observations(
                        canonical_identity, price, source, observed_at
                    ) VALUES(?,?,?,?)
                """, (
                    f"identity-{index}",
                    price,
                    store,
                    self.repository.iso(
                        self.now - timedelta(days=offset)
                    ),
                ))
            self.repository.conn.commit()

    def test_metricas_fila_top_e_grupos(self):
        snapshot = self.statistics.snapshot()
        metrics = snapshot.metrics
        self.assertEqual(metrics.total_analyzed, 3)
        self.assertEqual(metrics.total_approved, 2)
        self.assertEqual(metrics.total_discarded, 1)
        self.assertEqual(metrics.total_duplicate, 1)
        self.assertEqual(metrics.total_blocked, 1)
        self.assertEqual(metrics.total_selected_shadow, 1)
        self.assertEqual(metrics.maximum_score, 95)
        self.assertEqual(metrics.minimum_score, 30)
        self.assertEqual(snapshot.queue_counts["blocked"], 1)
        self.assertEqual(snapshot.top_offers[0]["score"], 95)
        self.assertEqual(
            {row["label"] for row in snapshot.by_store},
            {"Amazon", "Shopee"},
        )
        self.assertEqual(
            {row["label"] for row in snapshot.by_category},
            {"Tecnologia", "Casa"},
        )

    def test_filtros_loja_categoria_score_estado_data_e_produto(self):
        filters = OfferDashboardFilter(
            store="Amazon",
            category="Tecnologia",
            minimum_score=90,
            queue_status="selected_shadow",
            date_from=self.now,
            date_to=self.now + timedelta(hours=1),
            product_query="Produto 1",
        )
        snapshot = self.statistics.snapshot(filters)
        self.assertEqual(snapshot.metrics.total_analyzed, 1)
        self.assertEqual(snapshot.top_offers[0]["title"], "Produto 1")

    def test_inspector_retorna_diagnostico_historico_e_decisoes(self):
        pipeline_id = self.statistics.snapshot().top_offers[0][
            "pipeline_item_id"
        ]
        inspected = self.statistics.inspect(pipeline_id)
        self.assertEqual(inspected["history_samples"], 2)
        self.assertEqual(inspected["historical_minimum"], 101)
        self.assertIn("canonical_identity", inspected["diagnostic"])
        self.assertIsInstance(inspected["decisions"], list)

    def test_consulta_rejeita_escrita(self):
        with self.assertRaisesRegex(ValueError, "somente consultas"):
            self.repository.read_all("DELETE FROM offer_queue")

    def test_snapshot_com_banco_vazio(self):
        empty_path = Path(self.tempdir.name) / "empty.db"
        empty = OfferPipelineRepository(empty_path)
        empty.migrate()
        snapshot = OfferStatistics(empty).snapshot()
        empty.close()
        self.assertEqual(snapshot.metrics.total_analyzed, 0)
        self.assertEqual(snapshot.top_offers, ())

    def test_consulta_do_painel_tem_baixo_tempo(self):
        started = time.perf_counter()
        for _ in range(20):
            self.statistics.snapshot()
        elapsed_ms = (time.perf_counter() - started) * 1000
        self.assertLess(elapsed_ms / 20, 30)


if __name__ == "__main__":
    unittest.main()
