import os
from unittest.mock import patch
import unittest

from src.offers.activation import OfferActivationFlags


class OfferActivationFlagsTest(unittest.TestCase):

    def test_padrao_e_totalmente_legado_e_reversivel(self):
        names = (
            "OFFER_INTELLIGENT_SCHEDULER_ENABLED",
            "OFFER_COMPARE_WITH_LEGACY",
            "OFFER_CANARY_PERCENT",
            "OFFER_MIN_SCORE_TO_SEND",
            "OFFER_MAX_SEND_PER_HOUR",
            "OFFER_MAX_SEND_PER_DAY",
            "OFFER_ENABLE_ROLLBACK",
        )
        with patch.dict(os.environ, {}, clear=False):
            for name in names:
                os.environ.pop(name, None)
            flags = OfferActivationFlags.from_environment()
        self.assertFalse(flags.intelligent_scheduler_enabled)
        self.assertEqual(flags.mode, "legado")
        self.assertEqual(flags.canary_percent, 0)
        self.assertEqual(flags.minimum_score_to_send, 85)
        self.assertTrue(flags.enable_rollback)

    def test_carrega_limita_e_documenta_todas_as_flags(self):
        values = {
            "OFFER_INTELLIGENT_SCHEDULER_ENABLED": "True",
            "OFFER_COMPARE_WITH_LEGACY": "False",
            "OFFER_CANARY_PERCENT": "150",
            "OFFER_MIN_SCORE_TO_SEND": "87.5",
            "OFFER_MAX_SEND_PER_HOUR": "5",
            "OFFER_MAX_SEND_PER_DAY": "20",
            "OFFER_ENABLE_ROLLBACK": "False",
        }
        with patch.dict(os.environ, values):
            flags = OfferActivationFlags.from_environment()
        self.assertTrue(flags.intelligent_scheduler_enabled)
        self.assertFalse(flags.compare_with_legacy)
        self.assertEqual(flags.canary_percent, 100)
        self.assertEqual(flags.minimum_score_to_send, 87.5)
        self.assertEqual(flags.max_send_per_hour, 5)
        self.assertEqual(flags.max_send_per_day, 20)
        self.assertFalse(flags.enable_rollback)


if __name__ == "__main__":
    unittest.main()

