from datetime import datetime, timedelta, timezone
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from scripts.collect_price_history import write_collection_reports
from scripts.inspect_price_history import write_product_report
from src.database.offer_pipeline_repository import OfferPipelineRepository
from src.offers.identity import OfferIdentity
from src.offers.models import OfferCandidate
from src.price_history import (
    PriceHistoryConfig, RealPriceHistoryService, RealPriceObservation,
)
from src.price_history.money import money


class RealPriceHistoryTest(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "history.db"
        self.repository = OfferPipelineRepository(self.path)
        self.repository.migrate()
        self.config = PriceHistoryConfig()
        self.service = RealPriceHistoryService(
            self.repository, self.config
        )
        self.now = datetime(2026, 7, 26, 12, tzinfo=timezone.utc)

    def tearDown(self):
        self.repository.close()
        self.tempdir.cleanup()

    def observation(self, price="100.00", at=None, **changes):
        values = {
            "product_key": "MLB50957106",
            "store": "Mercado Livre",
            "canonical_identity": "stable-identity",
            "canonical_product_id": "MLB50957106",
            "canonical_url":
                "https://www.mercadolivre.com.br/p/MLB50957106",
            "title": "SSD Kingston NV3 1TB",
            "price": price,
            "currency": "BRL",
            "observed_at": at or self.now,
            "source": "mercado_livre_persistent_browser",
            "run_id": f"run-{(at or self.now).isoformat()}",
            "original_url":
                "https://www.mercadolivre.com.br/p/MLB50957106",
        }
        values.update(changes)
        return RealPriceObservation(**values)

    def test_primeira_observacao(self):
        result = self.service.record(self.observation())
        self.assertTrue(result.accepted)
        self.assertTrue(result.stored)
        self.assertEqual(
            self.service.analyze("MLB50957106").valid_observations, 1
        )

    def test_segunda_no_mesmo_instante_e_duplicata(self):
        self.service.record(self.observation())
        duplicate = self.service.record(self.observation(run_id="outro"))
        self.assertFalse(duplicate.accepted)
        self.assertEqual(duplicate.reason, "DUPLICATE_WITHIN_WINDOW")
        self.assertEqual(
            self.service.analyze("MLB50957106").valid_observations, 1
        )

    def test_mesmo_preco_apos_janela_e_armazenado(self):
        self.service.record(self.observation())
        later = self.service.record(self.observation(
            at=self.now + timedelta(hours=2)
        ))
        self.assertTrue(later.stored)
        self.assertEqual(
            self.service.analyze("MLB50957106").valid_observations, 2
        )

    def test_dias_distintos(self):
        self.service.record(self.observation())
        self.service.record(self.observation(
            at=self.now + timedelta(days=1)
        ))
        self.assertEqual(
            self.service.analyze("MLB50957106").distinct_days, 2
        )

    def test_produto_divergente(self):
        result = self.service.record(self.observation(
            product_key="MLB99999999"
        ))
        self.assertEqual(result.reason, "PRODUCT_IDENTITY_MISMATCH")

    def test_preco_invalido_e_zero(self):
        self.assertEqual(
            self.service.record(self.observation(price="invalido")).reason,
            "INVALID_PRICE",
        )
        self.assertEqual(
            self.service.record(self.observation(price="0")).reason,
            "INVALID_PRICE",
        )

    def test_separador_decimal_brasileiro(self):
        self.assertEqual(money("R$ 1.179,90"), Decimal("1179.90"))
        self.assertEqual(money("1.179"), Decimal("1179.00"))

    def test_outlier_e_auditado_sem_entrar_no_calculo(self):
        self.service.record(self.observation(price="100"))
        result = self.service.record(self.observation(
            price="300", at=self.now + timedelta(hours=2)
        ))
        self.assertEqual(result.reason, "OUTLIER_PERCENT")
        analysis = self.service.analyze("MLB50957106")
        self.assertEqual(analysis.valid_observations, 1)
        self.assertEqual(analysis.ignored_observations, 1)
        self.assertEqual(analysis.maturity, "ANOMALOUS_HISTORY")

    def test_minimo_maximo_media_mediana_e_variacao(self):
        config = PriceHistoryConfig(outlier_percent=1000)
        service = RealPriceHistoryService(self.repository, config)
        for index, price in enumerate(("100", "80", "90")):
            service.record(self.observation(
                price=price, at=self.now + timedelta(days=index)
            ))
        analysis = service.analyze("MLB50957106")
        self.assertEqual(analysis.minimum, Decimal("80.00"))
        self.assertEqual(analysis.maximum, Decimal("100.00"))
        self.assertEqual(analysis.average, Decimal("90.00"))
        self.assertEqual(analysis.median, Decimal("90.00"))
        self.assertEqual(
            analysis.variation_from_previous_percent,
            Decimal("12.50"),
        )

    def test_maturidade_insuficiente_e_suficiente(self):
        self.service.record(self.observation())
        self.assertEqual(
            self.service.analyze("MLB50957106").maturity,
            "INSUFFICIENT_HISTORY",
        )
        for index, price in enumerate(("99", "98", "97", "96"), 1):
            self.service.record(self.observation(
                price=price, at=self.now + timedelta(days=index)
            ))
        analysis = self.service.analyze("MLB50957106")
        self.assertEqual(analysis.maturity, "SUFFICIENT_HISTORY")
        self.assertTrue(
            analysis.score_signals["history_reliable_for_score"]
        )

    def test_score_recebe_somente_historico_suficiente(self):
        self.service.record(self.observation())
        signals = self.service.analyze(
            "MLB50957106"
        ).score_signals
        self.assertFalse(signals["history_reliable_for_score"])
        self.assertEqual(signals["historical_minimum"], "")
        self.assertFalse(signals["discount_verified"])

    def test_dry_run_nao_grava(self):
        before = len(self.repository.real_price_history("MLB50957106"))
        result = self.service.record(self.observation(), dry_run=True)
        after = len(self.repository.real_price_history("MLB50957106"))
        self.assertEqual(result.status, "WOULD_STORE")
        self.assertEqual(before, after)

    def test_identidade_ml_independe_de_pequena_mudanca_no_titulo(self):
        def identity(title):
            return OfferIdentity().identify(OfferCandidate.from_mapping({
                "loja": "Mercado Livre", "titulo": title,
                "preco": 100,
                "link": "https://www.mercadolivre.com.br/p/MLB50957106",
            })).signature
        self.assertEqual(
            identity("SSD Kingston 1TB"),
            identity("SSD Kingston 1TB promoção"),
        )

    def test_relatorios_nao_contem_segredos(self):
        secret = "https://meli.la/link-afiliado-secreto"
        analysis = self.service.analyze("MLB50957106")
        with tempfile.TemporaryDirectory() as directory:
            from scripts import collect_price_history as collection_module
            old = collection_module.OUTPUT
            collection_module.OUTPUT = Path(directory)
            try:
                paths = write_collection_reports([], analysis)
                product_paths = write_product_report(
                    "MLB50957106", asdict(analysis)
                )
            finally:
                collection_module.OUTPUT = old
            text = "\n".join(
                path.read_text(encoding="utf-8-sig")
                for path in (*paths, *product_paths)
            )
        self.assertNotIn(secret, text)

    def test_scripts_nao_importam_transportes(self):
        source = "\n".join(
            Path(path).read_text(encoding="utf-8").casefold()
            for path in (
                "scripts/collect_price_history.py",
                "scripts/inspect_price_history.py",
            )
        )
        for forbidden in (
            "src.core.notifier", "send_whatsapp", "evolution",
            "offercanary", "offerscheduler",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
