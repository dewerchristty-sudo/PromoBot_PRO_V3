from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from src.database.offer_repository import OfferRepository
from src.offers.identity import OfferIdentity
from src.offers.models import OfferCandidate, RankedOffer, ScoreResult
from src.offers.policy import OfferSchedulerPolicy
from src.offers.queue import OfferQueue
from src.offers.scheduler import OfferScheduler


class OfferSchedulerTest(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "scheduler.db"
        self.repository = OfferRepository(self.path)
        self.repository.migrate()
        self.now = datetime(2026, 7, 26, 12, tzinfo=timezone.utc)

    def tearDown(self):
        self.repository.close()
        self.tempdir.cleanup()

    def build(self, **changes):
        defaults = {
            "max_per_hour": 3,
            "max_per_day": 12,
            "minimum_interval_minutes": 0,
            "minimum_score": 70,
            "reservation_minutes": 10,
            "start_hour": 8,
            "end_hour": 22,
            "ranking_max_per_category": 1,
            "ranking_max_per_store": 2,
            "ranking_max_per_identity": 1,
        }
        defaults.update(changes)
        policy = OfferSchedulerPolicy(**defaults)
        queue = OfferQueue(self.repository, policy)
        scheduler = OfferScheduler(queue, policy)
        return queue, scheduler

    def add(
        self,
        queue,
        title,
        score=80,
        category=None,
        store=None,
        blocks=(),
        expires=None,
    ):
        category = category or f"Categoria {title}"
        store = store or (
            "Mercado Livre", "Amazon", "Shopee"
        )[sum(ord(character) for character in title) % 3]
        candidate = OfferCandidate(
            product_id=title,
            title=title,
            store=store,
            category=category,
            current_price=80,
            previous_price=100,
        )
        ranked = RankedOffer(
            candidate,
            ScoreResult(
                score,
                "oferta_excelente" if score >= 90 else "boa_oferta",
                {},
                1,
                6,
            ),
            OfferIdentity().identify(candidate),
        )
        return queue.enqueue_ranked(
            ranked,
            operational_blocks=blocks,
            expires_at=expires or self.now + timedelta(hours=12),
            available_at=self.now,
        )[0]

    def test_seleciona_ate_tres_e_quantidade_disponivel(self):
        for total in (1, 2, 4):
            with self.subTest(total=total):
                self.tearDown()
                self.setUp()
                queue, scheduler = self.build()
                for index in range(total):
                    self.add(queue, f"Produto {index}", 80 + index)
                decision = scheduler.run(self.now)
                self.assertEqual(decision.selected_count, min(total, 3))

    def test_nao_completa_com_oferta_fraca_e_respeita_score(self):
        queue, scheduler = self.build()
        self.add(queue, "Boa", 80)
        weak = self.add(queue, "Fraca", 49)
        decision = scheduler.run(self.now)
        self.assertEqual(decision.selected_count, 1)
        self.assertTrue(any(
            item.queue_item_id == weak.id
            and item.reason == "score_insuficiente"
            for item in decision.skipped_offers
        ))

    def test_oferta_excelente_tem_prioridade_e_ranking_deterministico(self):
        queue, scheduler = self.build(max_per_hour=1)
        self.add(queue, "Boa", 80)
        excellent = self.add(queue, "Excelente", 95)
        first = scheduler.run(self.now)
        self.assertEqual(first.selected_offers[0].id, excellent.id)

    def test_respeita_limite_diario(self):
        queue, scheduler = self.build(max_per_day=1, max_per_hour=3)
        self.add(queue, "Primeira", 90)
        self.assertEqual(scheduler.run(self.now).selected_count, 1)
        self.add(queue, "Segunda", 90)
        decision = scheduler.run(self.now + timedelta(hours=2))
        self.assertEqual(decision.selected_count, 0)
        self.assertIn("limite_diario", decision.reasons)

    def test_respeita_intervalo_minimo(self):
        queue, scheduler = self.build(minimum_interval_minutes=15)
        self.add(queue, "Primeira", 90)
        scheduler.run(self.now)
        self.add(queue, "Segunda", 90)
        decision = scheduler.run(self.now + timedelta(minutes=10))
        self.assertEqual(decision.selected_count, 0)
        self.assertIn("intervalo_minimo", decision.reasons)

    def test_nao_seleciona_fora_do_horario(self):
        queue, scheduler = self.build()
        self.add(queue, "Produto", 90)
        decision = scheduler.run(self.now.replace(hour=23))
        self.assertEqual(decision.selected_count, 0)
        self.assertIn("fora_do_horario", decision.reasons)

    def test_nao_seleciona_bloqueada_expirada_ou_duplicada(self):
        queue, scheduler = self.build()
        blocked = self.add(
            queue,
            "Bloqueada",
            95,
            blocks=("duplicidade_ativa",),
        )
        expired = self.add(
            queue,
            "Expirada",
            95,
            expires=self.now - timedelta(seconds=1),
        )
        decision = scheduler.run(self.now)
        self.assertEqual(decision.selected_count, 0)
        reasons = {
            item.queue_item_id: item.reason
            for item in decision.skipped_offers
        }
        self.assertEqual(reasons[blocked.id], "bloqueado")
        self.assertEqual(reasons[expired.id], "expirado")

    def test_respeita_diversidade_categoria_loja_e_identidade(self):
        queue, scheduler = self.build()
        self.add(
            queue, "Notebook A", 95,
            category="Tecnologia", store="Amazon",
        )
        self.add(
            queue, "Notebook B", 94,
            category="Tecnologia", store="Amazon",
        )
        self.add(
            queue, "Geladeira", 93,
            category="Casa", store="Amazon",
        )
        self.add(
            queue, "Perfume", 92,
            category="Beleza", store="Shopee",
        )
        decision = scheduler.run(self.now)
        self.assertEqual(
            {item.category for item in decision.selected_offers},
            {"Tecnologia", "Casa", "Beleza"},
        )
        self.assertLessEqual(
            sum(item.store == "Amazon" for item in decision.selected_offers),
            2,
        )

    def test_marca_selected_shadow_audita_e_nao_chama_notifier(self):
        queue, scheduler = self.build()
        item = self.add(queue, "Produto", 90)
        self.assertFalse(hasattr(scheduler, "notifier"))
        decision = scheduler.run(self.now)
        stored = self.repository.get(item.id)
        self.assertEqual(stored.status, "selected_shadow")
        self.assertTrue(decision.shadow_mode)
        self.assertFalse(decision.affects_current_flow)
        decisions = self.repository.decisions(item.id)
        self.assertTrue(any(
            row["new_status"] == "selected_shadow"
            and row["shadow_mode"] == 1
            for row in decisions
        ))


if __name__ == "__main__":
    unittest.main()
