import unittest

from src.offer_intelligence import OfferIntelligenceAnalyzer

from .fixtures import TEN_DAY_PRICES, TEST_PRODUCT_KEY
from .helpers import IsolatedHistory, valid_count


class RestartConsistencyTest(unittest.TestCase):

    def setUp(self):
        self.system = IsolatedHistory()

    def tearDown(self):
        self.system.close()

    def test_reinicio_reconstroi_mesmos_indicadores(self):
        for index, price in enumerate(TEN_DAY_PRICES[:6]):
            if index:
                self.system.clock.advance(days=1)
            self.system.record(price)
        before = OfferIntelligenceAnalyzer(
            self.system.repository
        ).analyze(TEST_PRODUCT_KEY, now=self.system.clock.now())
        self.system.restart()
        after = OfferIntelligenceAnalyzer(
            self.system.repository
        ).analyze(TEST_PRODUCT_KEY, now=self.system.clock.now())
        comparable = (
            "observation_count", "distinct_days", "minimum_price",
            "maximum_price", "average_price", "median_price", "trend",
            "confidence_index", "state", "states",
        )
        for name in comparable:
            self.assertEqual(getattr(before, name), getattr(after, name))

    def test_mesmo_run_id_duplicado_apos_reinicio(self):
        self.system.record("1000", run_id="same-run")
        self.system.restart()
        duplicate = self.system.record("1000", run_id="same-run")
        self.assertEqual(duplicate.reason, "DUPLICATE_WITHIN_WINDOW")
        self.assertEqual(valid_count(self.system), 1)
