from decimal import Decimal
import unittest

from src.offer_intelligence import OfferIntelligenceAnalyzer

from .fixtures import TEST_PRODUCT_KEY
from .helpers import IsolatedHistory


class TemporalPropertiesTest(unittest.TestCase):

    def test_propriedades_deterministicas(self):
        sequences = (
            ("100", "100", "100"),
            ("100", "90", "80", "70", "60"),
            ("60", "70", "80", "90", "100"),
            ("100", "80", "120", "90", "110"),
        )
        for sequence in sequences:
            with self.subTest(sequence=sequence):
                system = IsolatedHistory()
                try:
                    for index, price in enumerate(sequence):
                        if index:
                            system.clock.advance(days=1)
                        system.record(price)
                    result = OfferIntelligenceAnalyzer(
                        system.repository
                    ).analyze(TEST_PRODUCT_KEY, now=system.clock.now())
                    self.assertLessEqual(
                        result.minimum_price, result.maximum_price
                    )
                    self.assertGreaterEqual(
                        result.average_price, result.minimum_price
                    )
                    self.assertLessEqual(
                        result.average_price, result.maximum_price
                    )
                    self.assertGreaterEqual(result.confidence_index, 0)
                    self.assertLessEqual(
                        result.confidence_index, Decimal("100")
                    )
                    self.assertLessEqual(
                        result.distinct_days, result.observation_count
                    )
                finally:
                    system.close()
