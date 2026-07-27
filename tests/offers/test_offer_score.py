import unittest

from src.offers import OfferCandidate, OfferScore, OfferScorePolicy


class OfferScoreTest(unittest.TestCase):

    def setUp(self):
        self.scorer = OfferScore()

    def candidate(self, **changes):
        values = {
            "title": "Produto em oferta",
            "store": "Amazon",
            "current_price": 50.0,
            "previous_price": 100.0,
            "historical_minimum": 50.0,
            "price_sample_count": 5,
            "seller_name": "Loja Oficial",
            "seller_reputation": "excelente",
            "official_store": True,
            "category": "Tecnologia",
            "category_demand": "muito alta",
            "image_url": "https://example.com/image.jpg",
            "affiliate_link": "https://example.com/affiliate",
            "product_link": "https://example.com/product",
            "future_signals": {
                "history_reliable_for_score": True,
                "title_quality": "GOOD",
            },
        }
        values.update(changes)
        return OfferCandidate(**values)

    def test_desconto_de_cinquenta_porcento(self):
        self.assertEqual(
            self.scorer.calculate(self.candidate()).components["discount"],
            35.0,
        )

    def test_sem_preco_anterior_nao_inventa_desconto(self):
        result = self.scorer.calculate(self.candidate(
            previous_price=None,
            historical_reference_price=None,
            price_sample_count=0,
            future_signals={
                "history_reliable_for_score": False,
                "title_quality": "GOOD",
            },
        ))
        self.assertEqual(result.components["discount"], 0)

    def test_historico_so_pontua_quando_tem_evidencia_temporal(self):
        reliable = self.scorer.calculate(self.candidate())
        weak = self.scorer.calculate(self.candidate(
            future_signals={
                "history_reliable_for_score": False,
                "title_quality": "GOOD",
            }
        ))
        self.assertEqual(reliable.components["price_history"], 20)
        self.assertEqual(weak.components["price_history"], 0)

    def test_loja_e_reputacao(self):
        result = self.scorer.calculate(self.candidate())
        self.assertEqual(result.components["trusted_store"], 10)
        self.assertEqual(result.components["seller_reputation"], 10)

    def test_bonus_sao_limitados(self):
        result = self.scorer.calculate(self.candidate(
            has_coupon=True, free_shipping=True, cashback=True
        ))
        self.assertEqual(result.components["coupon"], 5)
        self.assertEqual(result.components["free_shipping"], 5)
        self.assertEqual(result.components["cashback"], 3)
        self.assertEqual(result.components["bonus"], 5)

    def test_total_fica_entre_zero_e_cem(self):
        maximum = self.scorer.calculate(self.candidate(
            previous_price_validated=True,
            has_coupon=True,
            free_shipping=True,
            cashback=True,
            rating=4.9,
            review_count=100,
            sold_count=1000,
            stock_available=True,
        ))
        minimum = OfferScore(
            OfferScorePolicy(coupon_points=-500)
        ).calculate(self.candidate(has_coupon=True))
        self.assertGreaterEqual(maximum.total, 90)
        self.assertLessEqual(maximum.total, 100)
        self.assertEqual(minimum.total, 0)

    def test_classificacoes_calibradas(self):
        policy = OfferScorePolicy()
        expected = {
            95: "oferta_excepcional",
            75: "oferta_muito_boa",
            65: "oferta_boa",
            55: "oferta_regular",
            39: "oferta_fraca_sem_evidencia",
        }
        for total, classification in expected.items():
            with self.subTest(total=total):
                self.assertEqual(policy.classify(total), classification)

    def test_sem_evidencia_promocional_tem_teto_39(self):
        result = self.scorer.calculate(self.candidate(
            previous_price=None,
            historical_reference_price=None,
            historical_minimum=None,
            price_sample_count=0,
            has_coupon=True,
            free_shipping=True,
            cashback=True,
            future_signals={
                "history_reliable_for_score": False,
                "title_quality": "GOOD",
            },
        ))
        self.assertLessEqual(result.total, 39)
        self.assertLess(result.confidence, 75)

    def test_link_afiliado_nao_altera_score(self):
        without = self.scorer.calculate(self.candidate(affiliate_link=""))
        with_link = self.scorer.calculate(self.candidate(
            affiliate_link="https://example.com/afiliado"
        ))
        self.assertEqual(without.total, with_link.total)
        self.assertEqual(without.components["affiliate_link"], 0)

    def test_confianca_promocional_e_separada(self):
        result = self.scorer.calculate(self.candidate())
        self.assertGreaterEqual(result.confidence, 0)
        self.assertLessEqual(result.confidence, 100)
        self.assertEqual(result.components["data_confidence"], 0)

    def test_nao_inventa_sinais_ausentes(self):
        result = self.scorer.calculate(OfferCandidate(
            title="Produto novo", store="Loja", current_price=100
        ))
        self.assertEqual(result.components["discount"], 0)
        self.assertEqual(result.components["price_history"], 0)
        self.assertEqual(result.components["popularity"], 0)
        self.assertEqual(result.components["availability"], 0)

    def test_desconto_suspeito_aplica_penalidade(self):
        result = self.scorer.calculate(self.candidate(
            current_price=5,
            previous_price=100,
            previous_price_validated=True,
        ))
        self.assertLess(result.components["penalties"], 0)
        self.assertTrue(any("suspeito" in reason for reason in result.reasons))


if __name__ == "__main__":
    unittest.main()
