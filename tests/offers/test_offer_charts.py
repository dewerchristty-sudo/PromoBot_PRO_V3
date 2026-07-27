import unittest

from src.offers.charts import OfferCharts
from src.offers.statistics import OfferMetrics


class OfferChartsTest(unittest.TestCase):

    def test_series_de_score_e_tempo(self):
        rows = [
            {
                "label": "2026-07-26T10:00",
                "average_score": 70,
                "average_processing_ms": 4.5,
            },
            {
                "label": "2026-07-26T11:00",
                "average_score": 80,
                "average_processing_ms": 5.5,
            },
        ]
        score = OfferCharts.score_over_time(rows)
        processing = OfferCharts.processing_time(rows)
        self.assertEqual(score.values, (70.0, 80.0))
        self.assertEqual(score.kind, "line")
        self.assertEqual(processing.values, (4.5, 5.5))

    def test_produtos_por_loja_categoria_e_aprovacao(self):
        rows = [
            {"label": "Amazon", "total": 3},
            {"label": "Shopee", "total": 2},
        ]
        grouped = OfferCharts.products_by_group("Por loja", rows)
        approval = OfferCharts.approval(OfferMetrics(
            total_analyzed=10,
            total_approved=7,
        ))
        self.assertEqual(grouped.labels, ("Amazon", "Shopee"))
        self.assertEqual(grouped.values, (3.0, 2.0))
        self.assertEqual(approval.values, (7.0, 3.0))

    def test_series_vazia_e_valida(self):
        series = OfferCharts.products_by_group("Vazio", [])
        self.assertEqual(series.labels, ())
        self.assertEqual(series.values, ())


if __name__ == "__main__":
    unittest.main()
