from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3
import tempfile
import unittest

from src.database.offer_repository import OfferRepository
from src.offers.models import QueueOffer


class OfferRepositoryTest(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "offers.db"
        self.repository = OfferRepository(self.path)
        self.repository.migrate()
        self.now = datetime(2026, 7, 26, 12, tzinfo=timezone.utc)

    def tearDown(self):
        self.repository.close()
        self.tempdir.cleanup()

    def offer(self, signature="promo-1"):
        return QueueOffer(
            id=None,
            evaluation_id="eval-1",
            product_id="1",
            canonical_identity="identity-1",
            promotion_signature=signature,
            title="Produto",
            store="Amazon",
            category="Tecnologia",
            current_price=80,
            previous_price=100,
            discount_percent=20,
            saving_amount=20,
            score=80,
            classification="boa_oferta",
            confidence=6,
            score_components={"discount": 15},
            available_at=self.now,
            expires_at=self.now + timedelta(hours=12),
            created_at=self.now,
        )

    def test_migracao_cria_tabelas_e_indices_e_e_idempotente(self):
        self.repository.migrate()
        tables = self.repository.table_names()
        indices = self.repository.index_names()
        self.assertTrue({
            "offer_queue",
            "offer_queue_decisions",
            "offer_scheduler_runs",
        }.issubset(tables))
        expected = {
            "idx_offer_queue_status",
            "idx_offer_queue_score",
            "idx_offer_queue_priority",
            "idx_offer_queue_available_at",
            "idx_offer_queue_expires_at",
            "idx_offer_queue_identity",
            "idx_offer_queue_promotion",
            "idx_offer_queue_reserved_by",
            "idx_offer_queue_reservation_expires",
            "idx_offer_queue_created_at",
        }
        self.assertTrue(expected.issubset(indices))

    def test_persistencia_apos_reiniciar_repositorio(self):
        item, created = self.repository.enqueue(self.offer())
        self.assertTrue(created)
        self.repository.close()
        self.repository = OfferRepository(self.path)
        self.repository.migrate()
        restored = self.repository.get(item.id)
        self.assertEqual(restored.title, "Produto")
        self.assertEqual(restored.status, "queued")

    def test_migracao_nao_altera_tabela_legada(self):
        self.repository.close()
        connection = sqlite3.connect(self.path)
        connection.execute(
            "CREATE TABLE produtos_legados(id INTEGER PRIMARY KEY, nome TEXT)"
        )
        connection.execute(
            "INSERT INTO produtos_legados(nome) VALUES('preservado')"
        )
        connection.commit()
        connection.close()
        self.repository = OfferRepository(self.path)
        self.repository.migrate()
        value = self.repository.conn.execute(
            "SELECT nome FROM produtos_legados"
        ).fetchone()[0]
        self.assertEqual(value, "preservado")

    def test_decisoes_preservam_status_anterior_novo_e_modo_sombra(self):
        item, _ = self.repository.enqueue(self.offer())
        self.repository.transition(
            item.id,
            ("queued",),
            "blocked",
            "imagem_ausente",
        )
        decisions = self.repository.decisions(item.id)
        last = decisions[-1]
        self.assertEqual(last["previous_status"], "queued")
        self.assertEqual(last["new_status"], "blocked")
        self.assertEqual(last["shadow_mode"], 1)


if __name__ == "__main__":
    unittest.main()
