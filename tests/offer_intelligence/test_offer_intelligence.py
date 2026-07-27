from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest

from scripts.inspect_offer_intelligence import inspect
from src.database.offer_pipeline_repository import OfferPipelineRepository
from src.offer_intelligence import (
    INTELLIGENCE_STATES, OfferIntelligenceAnalyzer,
    write_intelligence_reports,
)
from src.offer_intelligence.confidence import ConfidenceAnalyzer
from src.offer_intelligence.rarity import RarityAnalyzer
from src.offer_intelligence.trend import TrendAnalyzer


class OfferIntelligenceTest(unittest.TestCase):

    def setUp(self):
        self.now = datetime(2026, 7, 26, 15, tzinfo=timezone.utc)

    def row(self, price, day=0, row_id=1, **changes):
        value = {
            "id": row_id, "valid": 1, "product_key": "MLB50957106",
            "store": "Mercado Livre", "title": "SSD Kingston 1TB",
            "price": str(price),
            "observed_at": (self.now - timedelta(days=7-day)).isoformat(),
        }
        value.update(changes)
        return value

    def analyze(self, prices):
        rows = [
            self.row(price, day=index, row_id=index + 1)
            for index, price in enumerate(prices)
        ]
        return OfferIntelligenceAnalyzer().analyze(
            "MLB50957106", rows, now=self.now
        )

    def test_sem_historico_retorna_unknown(self):
        result = self.analyze([])
        self.assertEqual(result.state, "UNKNOWN")
        self.assertIsNone(result.current_price)
        self.assertEqual(result.operational_effect, "NONE")

    def test_uma_observacao_e_insuficiente(self):
        result = self.analyze(["100"])
        self.assertEqual(result.state, "INSUFFICIENT_HISTORY")
        self.assertEqual(result.minimum_price, Decimal("100.00"))
        self.assertEqual(result.maximum_price, Decimal("100.00"))

    def test_historico_em_construcao(self):
        result = self.analyze(["100", "95"])
        self.assertEqual(result.state, "BUILDING_HISTORY")
        self.assertIn("LOW_CONFIDENCE", result.states)

    def test_estatisticas_completas(self):
        result = self.analyze(["100", "80", "90", "70", "60"])
        self.assertEqual(result.minimum_price, Decimal("60.00"))
        self.assertEqual(result.maximum_price, Decimal("100.00"))
        self.assertEqual(result.average_price, Decimal("80.00"))
        self.assertEqual(result.median_price, Decimal("80.00"))
        self.assertEqual(result.current_price, Decimal("60.00"))

    def test_frequencias_de_reducao_e_aumento(self):
        result = self.analyze(["100", "90", "95", "80", "80"])
        self.assertEqual(result.reduction_frequency_percent, Decimal("50.00"))
        self.assertEqual(result.increase_frequency_percent, Decimal("25.00"))

    def test_tendencia_de_queda(self):
        result = self.analyze(["100", "95", "90", "85", "80"])
        self.assertEqual(result.trend, "FALLING")
        self.assertEqual(result.trend_change_percent, Decimal("-20.00"))

    def test_tendencia_estavel(self):
        result = TrendAnalyzer().calculate([
            Decimal("100"), Decimal("100.10"), Decimal("100.20")
        ])
        self.assertEqual(result.direction, "STABLE")

    def test_volatilidade_e_estabilidade(self):
        result = self.analyze(["100", "100", "100", "100", "100"])
        self.assertEqual(result.volatility_percent, Decimal("0.00"))
        self.assertEqual(result.stability_percent, Decimal("100.00"))
        self.assertIn("STABLE", result.states)

    def test_tempo_desde_queda_e_minimo(self):
        result = self.analyze(["100", "90", "95", "80", "85"])
        self.assertEqual(
            result.time_since_last_drop_seconds,
            int(timedelta(days=4).total_seconds()),
        )
        self.assertEqual(
            result.time_since_minimum_seconds,
            int(timedelta(days=4).total_seconds()),
        )

    def test_distancia_ate_minimo_e_media(self):
        result = self.analyze(["80", "100", "120", "100", "100"])
        self.assertEqual(result.distance_to_minimum_percent, Decimal("25.00"))
        self.assertEqual(result.distance_to_average_percent, Decimal("0.00"))

    def test_preco_raro_e_comum(self):
        rare = RarityAnalyzer().calculate(
            Decimal("50"), [
                Decimal("100"), Decimal("90"), Decimal("80"),
                Decimal("70"), Decimal("50"),
            ]
        )
        common = RarityAnalyzer().calculate(
            Decimal("100"), [
                Decimal("100"), Decimal("90"), Decimal("80"),
                Decimal("70"), Decimal("50"),
            ]
        )
        self.assertEqual(rare.state, "RARE_PRICE")
        self.assertEqual(rare.index, Decimal("80.00"))
        self.assertEqual(common.state, "COMMON_PRICE")

    def test_raridade_exige_tres_observacoes(self):
        result = RarityAnalyzer().calculate(
            Decimal("90"), [Decimal("100"), Decimal("90")]
        )
        self.assertEqual(result.state, "UNKNOWN")
        self.assertIsNone(result.index)

    def test_confianca_alta_com_amostra_madura(self):
        result = ConfidenceAnalyzer().calculate(
            10, 7, 14, Decimal("100")
        )
        self.assertEqual(result.index, Decimal("100.00"))
        self.assertEqual(result.state, "HIGH_CONFIDENCE")

    def test_todos_os_estados_documentados(self):
        expected = {
            "UNKNOWN", "INSUFFICIENT_HISTORY", "BUILDING_HISTORY",
            "STABLE", "HIGH_CONFIDENCE", "LOW_CONFIDENCE",
            "RARE_PRICE", "COMMON_PRICE",
        }
        self.assertEqual(INTELLIGENCE_STATES, expected)

    def test_linhas_invalidas_nao_entram_no_calculo(self):
        rows = [
            self.row("100", row_id=1),
            self.row("10", day=1, row_id=2, valid=0),
            self.row("90", day=2, row_id=3),
        ]
        result = OfferIntelligenceAnalyzer().analyze(
            "MLB50957106", rows, now=self.now
        )
        self.assertEqual(result.observation_count, 2)
        self.assertEqual(result.minimum_price, Decimal("90.00"))

    def test_repositorio_e_script_sao_somente_leitura(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = OfferPipelineRepository(
                Path(directory) / "history.db"
            )
            repository.migrate()
            before = repository.conn.total_changes
            result = inspect(
                "MLB50957106", repository=repository, now=self.now
            )
            after = repository.conn.total_changes
            repository.close()
        self.assertEqual(result.state, "UNKNOWN")
        self.assertEqual(before, after)

    def test_relatorios_exigidos(self):
        analysis = self.analyze(["100", "90", "80"])
        with tempfile.TemporaryDirectory() as directory:
            paths = write_intelligence_reports([analysis], directory)
            self.assertEqual(
                {path.name for path in paths},
                {
                    "offer_intelligence.json",
                    "offer_intelligence_summary.txt",
                    "product_MLB50957106_intelligence.json",
                },
            )
            payload = json.loads(paths[0].read_text(encoding="utf-8"))
            summary = paths[1].read_text(encoding="utf-8")
        self.assertEqual(payload["count"], 1)
        self.assertIn("Mensagens enviadas: 0", summary)

    def test_camada_nao_importa_score_scheduler_ou_transportes(self):
        source = "\n".join(
            path.read_text(encoding="utf-8").casefold()
            for path in (
                *Path("src/offer_intelligence").glob("*.py"),
                Path("scripts/inspect_offer_intelligence.py"),
            )
        )
        for forbidden in (
            "src.offers.score", "src.offers.scheduler",
            "src.collector_scheduler", "src.affiliates",
            "src.core.notifier", "whatsapp", "evolution", "pilot",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
