from datetime import datetime, timedelta, timezone
import unittest

from src.offers import OfferAnalysisPolicy, OfferHistory


class OfferHistoryTest(unittest.TestCase):

    def setUp(self):
        self.now = datetime(2026, 7, 26, 12, tzinfo=timezone.utc)
        self.history = OfferHistory(policy=OfferAnalysisPolicy(
            history_minimum_samples=3,
            history_window_days=90,
        ))

    def record_prices(self, *prices):
        for index, price in enumerate(prices):
            self.history.record(
                "produto",
                price,
                self.now - timedelta(days=len(prices) - index - 1),
            )

    def test_estatisticas_de_preco(self):
        self.record_prices(100, 80, 120, 60)
        result = self.history.analyze("produto", 60, self.now)
        self.assertEqual(result.minimum, 60)
        self.assertEqual(result.maximum, 120)
        self.assertEqual(result.average, 90)
        self.assertEqual(result.median, 90)
        self.assertEqual(result.sample_count, 4)

    def test_historico_insuficiente_com_menos_de_tres_amostras(self):
        self.record_prices(100, 90)
        result = self.history.analyze("produto", 90, self.now)
        self.assertFalse(result.reliable)

    def test_menor_preco_confiavel_com_tres_amostras(self):
        self.record_prices(100, 90, 80)
        result = self.history.analyze("produto", 80, self.now)
        self.assertTrue(result.reliable)
        self.assertTrue(result.is_historical_low)

    def test_preco_ate_cinco_porcento_acima_do_menor(self):
        self.record_prices(100, 80, 84)
        result = self.history.analyze("produto", 84, self.now)
        self.assertTrue(result.is_near_historical_low)
        self.assertFalse(result.is_historical_low)

    def test_precos_zero_negativo_e_nulo_sao_ignorados(self):
        for value in (0, -10, None):
            self.assertFalse(self.history.record("produto", value, self.now))
        self.assertEqual(
            self.history.analyze("produto", now=self.now).sample_count,
            0,
        )

    def test_observacoes_fora_da_janela_sao_ignoradas(self):
        self.history.record(
            "produto",
            10,
            self.now - timedelta(days=91),
        )
        self.history.record("produto", 20, self.now)
        result = self.history.analyze("produto", 20, self.now)
        self.assertEqual(result.sample_count, 1)
        self.assertEqual(result.minimum, 20)

    def test_variacao_em_relacao_ao_preco_anterior(self):
        self.record_prices(100, 90, 80)
        result = self.history.analyze("produto", 80, self.now)
        self.assertAlmostEqual(
            result.variation_from_previous_percent,
            -11.11,
            places=2,
        )

    def test_percentil_aproximado(self):
        self.record_prices(100, 80, 120, 60)
        result = self.history.analyze("produto", 80, self.now)
        self.assertEqual(result.percentile, 50.0)

    def test_mesmo_preco_no_mesmo_dia_nao_duplica(self):
        self.assertTrue(self.history.record("produto", 100, self.now))
        self.assertFalse(self.history.record(
            "produto", 100, self.now + timedelta(hours=2)
        ))
        self.assertTrue(self.history.record(
            "produto", 95, self.now + timedelta(hours=3)
        ))
        self.assertEqual(len(self.history.full_history("produto")), 2)

    def test_estatisticas_temporais_e_consultas(self):
        self.record_prices(100, 90, 80, 70)
        result = self.history.analyze("produto", 70, self.now)
        self.assertEqual(result.observed_days, 4)
        self.assertEqual(result.first_price, 100)
        self.assertEqual(result.last_price, 70)
        self.assertGreater(result.standard_deviation, 0)
        self.assertEqual(len(self.history.last_7_days(
            "produto", self.now
        )), 4)
        self.assertEqual(self.history.minimum_price("produto"), 70)
        self.assertEqual(self.history.maximum_price("produto"), 100)
        self.assertEqual(self.history.average_price("produto"), 85)

    def test_tendencia_recorde_eventos_e_variacoes(self):
        self.record_prices(100, 100, 90, 70)
        result = self.history.analyze("produto", 70, self.now)
        self.assertEqual(result.trend, "caiu")
        self.assertTrue(result.is_new_record)
        self.assertIn("novo_recorde_preco", result.events)
        self.assertIn("queda_20_porcento", result.events)
        self.assertLess(result.daily_variation_percent, 0)

    def test_confianca_temporal_por_dias(self):
        expected = {
            1: "baixa", 3: "media", 7: "boa", 15: "alta",
            30: "muito_alta", 90: "maxima",
        }
        for days, confidence in expected.items():
            with self.subTest(days=days):
                self.assertEqual(
                    self.history.temporal_confidence(days), confidence
                )


if __name__ == "__main__":
    unittest.main()
