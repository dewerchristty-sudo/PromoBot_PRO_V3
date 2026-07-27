import unittest

from src.offers import OfferScorePolicy


class OfferScorePolicyTest(unittest.TestCase):

    def test_faixas_iniciais_de_desconto(self):
        policy = OfferScorePolicy()
        cases = {
            50: 35,
            49.99: 30,
            40: 30,
            39.99: 25,
            30: 25,
            29.99: 15,
            20: 15,
            19.99: 5,
            10: 5,
            9.99: 0,
        }
        for discount, expected in cases.items():
            with self.subTest(discount=discount):
                self.assertEqual(
                    policy.points_for_discount(discount),
                    expected,
                )

    def test_politica_e_versionada_e_configuravel(self):
        policy = OfferScorePolicy(
            policy_version=2,
            coupon_points=8,
        )
        self.assertEqual(policy.policy_version, 2)
        self.assertEqual(policy.coupon_points, 8)


if __name__ == "__main__":
    unittest.main()
