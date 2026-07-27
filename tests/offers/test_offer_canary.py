from unittest.mock import patch
import unittest

from src.offers.activation import OfferActivationFlags
from src.offers.canary import OfferCanaryController


class FakeCanaryRepository:

    def __init__(self, score=95, approved=True, duplicate_type=""):
        self.analysis = {
            "score": score,
            "filter_approved": approved,
            "duplicate_type": duplicate_type,
        }
        self.rows = []
        self.sent = set()
        self.fail_decision = False

    def canary_send_counts(self, _now):
        if self.fail_decision:
            raise RuntimeError("banco indisponivel")
        return {"hour": 0, "day": 0}

    def latest_offer_analysis(self, _title, _store, _identity):
        return self.analysis

    def canary_identity_was_sent(self, identity):
        return identity in self.sent

    def record_canary_decisions(self, rows):
        self.rows.extend(rows)
        self.sent.update(
            row["identity"] for row in rows if row["sent"]
        )


def flags(percent, **changes):
    values = {
        "intelligent_scheduler_enabled": True,
        "compare_with_legacy": True,
        "canary_percent": percent,
        "minimum_score_to_send": 85,
        "max_send_per_hour": 3,
        "max_send_per_day": 12,
        "enable_rollback": True,
    }
    values.update(changes)
    return OfferActivationFlags(**values)


def alert(title="Produto"):
    return {
        "titulo": title,
        "loja": "Amazon",
        "categoria": "Tecnologia",
        "link": f"https://example.com/{title}",
    }


class OfferCanaryControllerTest(unittest.TestCase):

    def send_spy(self):
        calls = []

        def send(items):
            calls.append(list(items))
            return "Enviado por: WhatsApp"

        return calls, send

    def test_canary_zero_usa_exatamente_fluxo_legado(self):
        repository = FakeCanaryRepository()
        calls, send = self.send_spy()
        result = OfferCanaryController(
            repository, flags(0)
        ).execute([alert()], send)
        self.assertEqual(result, "Enviado por: WhatsApp")
        self.assertEqual(len(calls), 1)
        self.assertEqual(repository.rows, [])

    def assert_boundary(self, percent):
        repository = FakeCanaryRepository()
        controller = OfferCanaryController(repository, flags(percent))
        with patch.object(
            OfferCanaryController,
            "bucket",
            staticmethod(lambda _identity: percent - 1),
        ):
            intelligent = controller.decide([alert("Dentro")])[0]
        with patch.object(
            OfferCanaryController,
            "bucket",
            staticmethod(lambda _identity: percent),
        ):
            legacy = controller.decide([alert("Fora")])[0]
        self.assertEqual(intelligent.scheduler, "inteligente")
        self.assertEqual(legacy.scheduler, "legado")

    def test_canary_5_porcento(self):
        self.assert_boundary(5)

    def test_canary_10_porcento(self):
        self.assert_boundary(10)

    def test_canary_50_porcento(self):
        self.assert_boundary(50)

    def test_canary_100_porcento(self):
        repository = FakeCanaryRepository()
        calls, send = self.send_spy()
        result = OfferCanaryController(
            repository, flags(100)
        ).execute([alert()], send)
        self.assertEqual(result, "Enviado por: WhatsApp")
        self.assertEqual(len(calls[0]), 1)
        self.assertEqual(repository.rows[0]["scheduler"], "inteligente")
        self.assertTrue(repository.rows[0]["sent"])

    def test_score_baixo_nao_e_enviado_pelo_inteligente(self):
        repository = FakeCanaryRepository(score=70)
        calls, send = self.send_spy()
        result = OfferCanaryController(
            repository, flags(100)
        ).execute([alert()], send)
        self.assertTrue(result.startswith("Nenhum envio:"))
        self.assertEqual(calls, [])
        self.assertEqual(
            repository.rows[0]["reason"], "score_insuficiente"
        )

    def test_rollback_antes_do_transporte_devolve_tudo_ao_legado(self):
        repository = FakeCanaryRepository()
        repository.fail_decision = True
        calls, send = self.send_spy()
        result = OfferCanaryController(
            repository, flags(100)
        ).execute([alert("A"), alert("B")], send)
        self.assertEqual(result, "Enviado por: WhatsApp")
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(calls[0]), 2)
        self.assertTrue(all(
            row["scheduler"] == "legado_rollback"
            for row in repository.rows
        ))

    def test_falha_durante_transporte_nao_reenvia(self):
        repository = FakeCanaryRepository()
        calls = []

        def failing_send(items):
            calls.append(list(items))
            raise RuntimeError("canal fora")

        result = OfferCanaryController(
            repository, flags(100)
        ).execute([alert()], failing_send)
        self.assertTrue(result.startswith("Falha ao enviar:"))
        self.assertEqual(len(calls), 1)
        self.assertIn(
            "falha_transporte_sem_reenvio",
            repository.rows[0]["rollback_reason"],
        )

    def test_duplicidade_no_lote_so_envia_uma_vez(self):
        repository = FakeCanaryRepository()
        calls, send = self.send_spy()
        item = alert()
        OfferCanaryController(
            repository, flags(100)
        ).execute([item, dict(item)], send)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(calls[0]), 1)
        self.assertEqual(
            [row["sent"] for row in repository.rows],
            [True, False],
        )

    def test_comparacao_registra_decisoes_e_diferencas(self):
        repository = FakeCanaryRepository(score=60)
        OfferCanaryController(
            repository, flags(100)
        ).execute([alert()], lambda _items: "Enviado por: WhatsApp")
        row = repository.rows[0]
        self.assertEqual(row["legacy_decision"], "enviar")
        self.assertEqual(row["intelligent_decision"], "aguardar")
        self.assertEqual(row["difference"], "sim")
        self.assertGreaterEqual(row["decision_ms"], 0)
        self.assertIn("minimum_score_to_send", row["flags_json"])


if __name__ == "__main__":
    unittest.main()

