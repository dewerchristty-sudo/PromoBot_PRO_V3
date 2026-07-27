from datetime import datetime, timedelta, timezone
from decimal import Decimal
import unittest

from src.offer_intelligence import OfferIntelligenceAnalyzer

from .fixtures import TEN_DAY_PRICES, TEST_PRODUCT_KEY
from .helpers import IsolatedHistory, rejection_count, valid_count


class MultiDayPriceHistoryTest(unittest.TestCase):

    def setUp(self):
        self.system = IsolatedHistory()
        self.system.assert_isolated()

    def tearDown(self):
        self.system.close()

    def test_evolucao_real_de_dez_dias(self):
        maturities = []
        intelligence_states = []
        for index, price in enumerate(TEN_DAY_PRICES):
            if index:
                self.system.clock.advance(days=1)
            decision = self.system.record(price)
            self.assertTrue(decision.stored)
            maturity = self.system.service.analyze(TEST_PRODUCT_KEY)
            intelligence = OfferIntelligenceAnalyzer(
                self.system.repository
            ).analyze(TEST_PRODUCT_KEY, now=self.system.clock.now())
            maturities.append(maturity.maturity)
            intelligence_states.append(intelligence.state)
        history = self.system.service.analyze(TEST_PRODUCT_KEY)
        intelligence = OfferIntelligenceAnalyzer(
            self.system.repository
        ).analyze(TEST_PRODUCT_KEY, now=self.system.clock.now())
        self.assertEqual(valid_count(self.system), 10)
        self.assertEqual(history.distinct_days, 10)
        self.assertEqual(history.minimum, Decimal("1049.90"))
        self.assertEqual(history.maximum, Decimal("1159.90"))
        self.assertEqual(history.average, Decimal("1117.90"))
        self.assertEqual(history.median, Decimal("1114.90"))
        self.assertTrue(history.real_drop_confirmed)
        self.assertEqual(maturities[0], "INSUFFICIENT_HISTORY")
        self.assertIn("BUILDING_HISTORY", maturities)
        self.assertEqual(maturities[-1], "STABLE_HISTORY")
        self.assertEqual(intelligence_states[0], "INSUFFICIENT_HISTORY")
        self.assertIn("BUILDING_HISTORY", intelligence_states)
        self.assertEqual(intelligence.state, "STABLE")
        self.assertEqual(intelligence.trend, "FALLING")
        self.assertEqual(intelligence.rarity_percentile, Decimal("10.00"))
        self.assertIn("RARE_PRICE", intelligence.states)

    def test_matriz_de_deduplicacao_nao_muda_indicadores(self):
        first = self.system.record("1000")
        self.assertTrue(first.stored)
        baseline = OfferIntelligenceAnalyzer(
            self.system.repository
        ).analyze(TEST_PRODUCT_KEY, now=self.system.clock.now())
        same = self.system.record("1000", run_id="same-instant")
        self.system.clock.advance(minutes=30)
        within = self.system.record("1000", run_id="within-window")
        different = self.system.record("999", run_id="different-price")
        self.assertEqual(same.reason, "DUPLICATE_WITHIN_WINDOW")
        self.assertEqual(within.reason, "DUPLICATE_WITHIN_WINDOW")
        self.assertEqual(different.reason, "MIN_INTERVAL_NOT_REACHED")
        current = OfferIntelligenceAnalyzer(
            self.system.repository
        ).analyze(TEST_PRODUCT_KEY, now=self.system.clock.now())
        self.assertEqual(current.observation_count, baseline.observation_count)
        self.assertEqual(current.confidence_index, baseline.confidence_index)
        self.system.clock.advance(minutes=31)
        accepted = self.system.record("1000", run_id="after-window")
        self.assertTrue(accepted.stored)
        self.assertEqual(valid_count(self.system), 2)

    def test_dias_distintos_usam_fuso_de_sao_paulo(self):
        first = datetime(2026, 1, 6, 1, 30, tzinfo=timezone.utc)
        second = datetime(2026, 1, 6, 3, 30, tzinfo=timezone.utc)
        self.system.record("1000", at=first)
        self.system.record("999", at=second)
        history = self.system.service.analyze(TEST_PRODUCT_KEY)
        intelligence = OfferIntelligenceAnalyzer(
            self.system.repository
        ).analyze(TEST_PRODUCT_KEY, now=second + timedelta(hours=1))
        self.assertEqual(history.distinct_days, 2)
        self.assertEqual(intelligence.distinct_days, 2)

    def test_outliers_sao_auditados_e_nao_contaminam(self):
        for day, price in enumerate(("1000", "990", "980")):
            if day:
                self.system.clock.advance(days=1)
            self.system.record(price)
        before = OfferIntelligenceAnalyzer(
            self.system.repository
        ).analyze(TEST_PRODUCT_KEY, now=self.system.clock.now())
        for price in ("1.17", "2000", "0", "-10"):
            self.system.clock.advance(days=1)
            self.system.record(price)
        after = OfferIntelligenceAnalyzer(
            self.system.repository
        ).analyze(TEST_PRODUCT_KEY, now=self.system.clock.now())
        self.assertEqual(before.minimum_price, after.minimum_price)
        self.assertEqual(before.observation_count, after.observation_count)
        self.assertEqual(valid_count(self.system), 3)
        self.assertEqual(rejection_count(self.system), 4)
        reasons = {
            row["reason"] for row in
            self.system.repository.price_history_rejections(TEST_PRODUCT_KEY)
        }
        self.assertIn("OUTLIER_PERCENT", reasons)
        self.assertIn("INVALID_PRICE", reasons)
