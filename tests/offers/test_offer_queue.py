from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import threading
import unittest

from src.database.offer_repository import OfferRepository
from src.offers.identity import OfferIdentity
from src.offers.models import OfferCandidate, RankedOffer, ScoreResult
from src.offers.policy import OfferSchedulerPolicy
from src.offers.queue import OfferQueue


class OfferQueueTest(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "queue.db"
        self.repository = OfferRepository(self.path)
        self.repository.migrate()
        self.policy = OfferSchedulerPolicy(
            default_expiration_hours=12,
            reservation_minutes=10,
        )
        self.queue = OfferQueue(self.repository, self.policy)
        self.now = datetime.now(timezone.utc)

    def tearDown(self):
        self.repository.close()
        self.tempdir.cleanup()

    def ranked(self, title="Produto A", score=80, price=80):
        candidate = OfferCandidate(
            product_id=title,
            title=title,
            store="Amazon",
            category="Tecnologia",
            current_price=price,
            previous_price=100,
        )
        return RankedOffer(
            candidate=candidate,
            score=ScoreResult(
                score,
                "boa_oferta",
                {"discount": 15},
                1,
                6,
            ),
            identity=OfferIdentity().identify(candidate),
        )

    def test_inserir_evitar_duplicidade_e_atualizar_prioridade(self):
        first, created = self.queue.enqueue_ranked(self.ranked())
        second, created_again = self.queue.enqueue_ranked(self.ranked(score=90))
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(first.id, second.id)
        updated = self.queue.update_priority(first.id, 999)
        self.assertEqual(updated.priority, 999)

    def test_bloquear_desbloquear_descartar_e_registrar_erro(self):
        item, _ = self.queue.enqueue_ranked(self.ranked())
        blocked = self.queue.block(item.id, "imagem_ausente")
        self.assertEqual(blocked.status, "blocked")
        self.assertEqual(blocked.blocked_reason, "imagem_ausente")
        queued = self.queue.unblock(item.id)
        self.assertEqual(queued.status, "queued")
        failed = self.queue.fail(queued.id, "erro de teste")
        self.assertEqual(failed.status, "failed")
        self.assertEqual(failed.last_error, "erro de teste")
        requeued = self.queue.transition(failed.id, "queued", "tentar novamente")
        discarded = self.queue.discard(requeued.id, "score insuficiente")
        self.assertEqual(discarded.status, "discarded")

    def test_consultar_por_status(self):
        queued, _ = self.queue.enqueue_ranked(self.ranked("Produto A"))
        blocked, _ = self.queue.enqueue_ranked(
            self.ranked("Produto B"),
            operational_blocks=("link_afiliado_ausente",),
        )
        self.assertEqual(
            [item.id for item in self.queue.list(("queued",))],
            [queued.id],
        )
        self.assertEqual(
            [item.id for item in self.queue.list(("blocked",))],
            [blocked.id],
        )

    def test_transicoes_validas_e_invalida(self):
        item, _ = self.queue.enqueue_ranked(self.ranked())
        reservation_now = item.available_at
        reserved = self.repository.reserve_ids(
            [item.id],
            "worker",
            reservation_now,
            reservation_now + timedelta(minutes=10),
            "run",
        )[0]
        self.assertEqual(reserved.status, "reserved")
        selected = self.queue.select_shadow(reserved.id, "run")
        self.assertEqual(selected.status, "selected_shadow")
        with self.assertRaisesRegex(ValueError, "Transição inválida"):
            self.queue.transition(selected.id, "queued")

    def test_blocked_pode_voltar_e_expired_exige_operacao_explicita(self):
        item, _ = self.queue.enqueue_ranked(
            self.ranked(),
            operational_blocks=("imagem_ausente",),
        )
        self.assertEqual(self.queue.unblock(item.id).status, "queued")
        self.repository.transition(
            item.id,
            ("queued",),
            "expired",
            "teste",
        )
        with self.assertRaisesRegex(ValueError, "Transição inválida"):
            self.queue.transition(item.id, "queued")
        restored = self.queue.requeue_expired_explicitly(
            item.id,
            self.now + timedelta(hours=1),
        )
        self.assertEqual(restored.status, "queued")

    def test_reavaliacao_corrige_bloqueio_sem_duplicar_registro(self):
        blocked, created = self.queue.enqueue_ranked(
            self.ranked(),
            operational_blocks=("imagem_ausente",),
        )
        ready, created_again = self.queue.enqueue_ranked(self.ranked())
        self.assertTrue(created)
        self.assertFalse(created_again)
        self.assertEqual(blocked.id, ready.id)
        self.assertEqual(ready.status, "queued")
        self.assertEqual(ready.blocked_reason, "")

    def test_reserva_atomica_dupla_e_prazo_limitado_pela_oferta(self):
        expires = self.now + timedelta(minutes=5)
        item, _ = self.queue.enqueue_ranked(
            self.ranked(),
            expires_at=expires,
        )
        reservation_now = item.available_at
        repository_two = OfferRepository(self.path)
        repository_two.migrate()
        results = []

        def reserve(repository, worker):
            values = repository.reserve_ids(
                [item.id],
                worker,
                reservation_now,
                reservation_now + timedelta(minutes=10),
                worker,
            )
            results.append(values)

        threads = [
            threading.Thread(target=reserve, args=(self.repository, "a")),
            threading.Thread(target=reserve, args=(repository_two, "b")),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        repository_two.close()
        self.assertEqual(sum(bool(value) for value in results), 1)
        reserved = self.repository.get(item.id)
        self.assertEqual(reserved.status, "reserved")
        self.assertEqual(reserved.reservation_expires_at, expires)

    def test_reserva_vencida_e_liberada(self):
        item, _ = self.queue.enqueue_ranked(self.ranked())
        reservation_now = item.available_at
        self.repository.reserve_ids(
            [item.id],
            "worker",
            reservation_now,
            reservation_now + timedelta(minutes=1),
            "run",
        )
        released = self.queue.release_expired_reservations(
            reservation_now + timedelta(minutes=2)
        )
        self.assertEqual(released, 1)
        self.assertEqual(self.repository.get(item.id).status, "queued")

    def test_oferta_vencida_e_marcada_expired(self):
        item, _ = self.queue.enqueue_ranked(
            self.ranked(),
            expires_at=self.now - timedelta(seconds=1),
        )
        self.assertEqual(self.queue.expire_due(self.now), 1)
        self.assertEqual(self.repository.get(item.id).status, "expired")


if __name__ == "__main__":
    unittest.main()
