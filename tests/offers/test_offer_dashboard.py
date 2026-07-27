import unittest

from src.ui.offer_dashboard import OfferDashboard
from src.ui.offer_inspector import OfferInspector


class OfferDashboardTest(unittest.TestCase):

    def test_dashboard_declara_cards_profissionais(self):
        fields = {field for _title, field in OfferDashboard.CARD_FIELDS}
        self.assertTrue({
            "total_analyzed",
            "total_approved",
            "total_discarded",
            "total_duplicate",
            "total_blocked",
            "total_queued",
            "total_selected_shadow",
            "average_score",
            "maximum_score",
            "average_processing_ms",
        }.issubset(fields))

    def test_formatacao_monetaria(self):
        self.assertEqual(OfferDashboard.money(1299.9), "R$ 1.299,90")
        self.assertEqual(OfferInspector.money(99.5), "R$ 99,50")

    def test_painel_e_inspetor_nao_possuem_metodos_de_envio(self):
        forbidden = {"send", "send_alerts", "notifier", "whatsapp"}
        self.assertFalse(forbidden & set(OfferDashboard.__dict__))
        self.assertFalse(forbidden & set(OfferInspector.__dict__))


if __name__ == "__main__":
    unittest.main()
