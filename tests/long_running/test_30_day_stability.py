import unittest

from .scenarios import thirty_day_scenario


class ThirtyDayStabilityTest(unittest.TestCase):

    def test_trinta_dias_sem_espera_ou_efeito_operacional(self):
        result = thirty_day_scenario()
        self.assertEqual(result["marker"], "SIMULATED_TEST_DATA")
        self.assertEqual(result["scheduled_slots"], 90)
        self.assertEqual(result["collection_attempts"], 124)
        self.assertEqual(result["valid_observations"], 87)
        self.assertEqual(result["duplicates"], 30)
        self.assertEqual(result["rejections"], 33)
        self.assertEqual(result["outliers"], 3)
        self.assertEqual(result["failures"], 4)
        self.assertEqual(result["retries"], 4)
        self.assertEqual(result["restarts"], 4)
        self.assertEqual(result["distinct_days"], 30)
        # A regra existente sinaliza a presença auditada de qualquer outlier.
        self.assertEqual(result["history_maturity"], "ANOMALOUS_HISTORY")
        self.assertEqual(result["intelligence_state"], "STABLE")
        self.assertEqual(result["operational_calls"], 0)
