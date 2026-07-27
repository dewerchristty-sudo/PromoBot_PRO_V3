from datetime import datetime, timezone
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock

from src.affiliates.config import AffiliateConfig, StoreAffiliateConfig
from src.affiliates.manager import AffiliateManager
from src.database.offer_pipeline_repository import OfferPipelineRepository
from src.offers.pipeline import OfferPipeline
from src.offers.policy import OfferSchedulerPolicy
from src.offers.queue import OfferQueue
from src.offers.scheduler import OfferScheduler


class OfferPipelineTest(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "pipeline.db"
        self.repository = OfferPipelineRepository(self.path)
        self.repository.migrate()
        policy = OfferSchedulerPolicy(
            minimum_interval_minutes=0,
            start_hour=0,
            end_hour=0,
        )
        queue = OfferQueue(self.repository, policy)
        scheduler = OfferScheduler(queue, policy)
        affiliate_manager = AffiliateManager(AffiliateConfig(
            mercado_livre=StoreAffiliateConfig(),
            amazon=StoreAffiliateConfig(associate_tag="achadinhos-20"),
            shopee=StoreAffiliateConfig(),
            cache_path=Path(self.tempdir.name) / "affiliates.db",
            cache_ttl_hours=24,
        ))
        self.pipeline = OfferPipeline(
            self.repository,
            queue=queue,
            scheduler=scheduler,
            affiliate_manager=affiliate_manager,
        )
        self.now = datetime(2026, 7, 26, 12, tzinfo=timezone.utc)

    def tearDown(self):
        self.pipeline.affiliate_manager.close()
        self.repository.close()
        self.tempdir.cleanup()

    def product(self, **changes):
        values = {
            "id": 1,
            "titulo": "SSD Kingston NV3 1TB",
            "loja": "Amazon",
            "preco": "299,90",
            "preco_valor": 299.90,
            "preco_antigo": "399,90",
            "imagem": "https://example.com/ssd.jpg",
            "affiliate_link": "",
            "link": "https://www.amazon.com.br/dp/B000000001",
            "categoria_manual": "Tecnologia",
            "official_store": True,
            "seller_reputation": "excelente",
            "category_demand": "muito alta",
        }
        values.update(changes)
        return values

    def test_integracao_completa_em_modo_sombra(self):
        result = self.pipeline.process_batch(
            [self.product()],
            self.now,
        )
        item = result.items[0]
        self.assertEqual(result.metrics.received_count, 1)
        self.assertEqual(result.metrics.valid_count, 1)
        self.assertIsNotNone(item.analysis.identity)
        self.assertEqual(item.analysis.history.sample_count, 1)
        self.assertGreater(item.analysis.score.total, 0)
        self.assertIsNotNone(item.queue_item)
        self.assertTrue(result.shadow_mode)
        self.assertFalse(result.affects_current_flow)

    def test_produto_sem_categoria_e_sem_imagem_fica_bloqueado(self):
        result = self.pipeline.process_batch([
            self.product(
                categoria_manual="",
                imagem="",
            )
        ], self.now)
        item = result.items[0]
        self.assertEqual(item.queue_item.status, "blocked")
        self.assertIn(
            "imagem_ausente",
            item.analysis.filtering.operational_blocks,
        )

    def test_produto_sem_historico_comeca_com_uma_amostra(self):
        item = self.pipeline.process_batch(
            [self.product()],
            self.now,
        ).items[0]
        self.assertEqual(item.analysis.history.sample_count, 1)
        self.assertFalse(item.analysis.history.reliable)

    def test_produto_repetido_e_detectado(self):
        self.pipeline.process_batch([self.product()], self.now)
        repeated = self.pipeline.process_batch(
            [self.product()],
            self.now,
        ).items[0]
        self.assertTrue(repeated.analysis.duplicate.is_duplicate)
        self.assertGreaterEqual(
            self.pipeline.process_batch(
                [self.product()],
                self.now,
            ).metrics.duplicate_count,
            1,
        )

    def test_produto_excelente_medio_e_descartado(self):
        excellent = self.product(
            id=1, link="https://www.amazon.com.br/dp/B000000001"
        )
        medium = self.product(
            id=2,
            titulo="Produto médio",
            link="https://www.amazon.com.br/dp/B000000002",
            preco_valor=90,
            preco="90,00",
            preco_antigo="100,00",
            official_store=False,
            seller_reputation="",
            category_demand="",
        )
        invalid = self.product(
            id=3,
            titulo="Produto inválido",
            link="https://www.amazon.com.br/dp/B000000003",
            preco=0,
            preco_valor=0,
        )
        result = self.pipeline.process_batch(
            [excellent, medium, invalid],
            self.now,
        )
        statuses = {
            item.analysis.candidate.title: item.queue_item.status
            for item in result.items
            if item.analysis and item.queue_item
        }
        self.assertIn(
            statuses["SSD Kingston NV3 1TB"],
            {"queued", "selected_shadow"},
        )
        self.assertEqual(statuses["Produto inválido"], "discarded")
        self.assertGreaterEqual(result.metrics.discarded_count, 1)

    def test_diagnostico_e_metricas_sao_persistidos(self):
        result = self.pipeline.process_batch([self.product()], self.now)
        runs = self.repository.latest_runs()
        items = self.repository.items_for_run(result.run_id)
        self.assertEqual(runs[0]["run_id"], result.run_id)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["shadow_mode"], 1)
        self.assertEqual(items[0]["affects_current_flow"], 0)
        self.assertIn("canonical_identity", items[0]["diagnostic_json"])

    def test_falha_isolada_nao_interrompe_lote(self):
        original = self.pipeline.service.analyze
        calls = {"count": 0}

        def fail_once(product, now=None):
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("falha isolada")
            return original(product, now)

        self.pipeline.service.analyze = fail_once
        result = self.pipeline.process_batch(
            [self.product(id=1), self.product(
                id=2,
                titulo="Outro produto",
                link="https://www.amazon.com.br/dp/B000000004",
            )],
            self.now,
        )
        self.assertIn("falha isolada", result.items[0].error)
        self.assertIsNotNone(result.items[1].analysis)

    def test_processamento_em_lote_tem_baixo_custo_por_produto(self):
        products = [
            self.product(
                id=index,
                titulo=f"Produto desempenho {index}",
                link=f"https://example.com/{index}",
            )
            for index in range(30)
        ]
        started = time.perf_counter()
        result = self.pipeline.process_batch(products, self.now)
        elapsed_ms = (time.perf_counter() - started) * 1000
        per_product = elapsed_ms / len(products)
        self.assertEqual(result.metrics.received_count, 30)
        self.assertLess(per_product, 25)

    def test_pipeline_nao_possui_notifier(self):
        self.assertFalse(hasattr(self.pipeline, "notifier"))
        self.assertFalse(hasattr(self.pipeline.scheduler, "notifier"))


if __name__ == "__main__":
    unittest.main()
