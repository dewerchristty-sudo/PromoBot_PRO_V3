import logging
import os
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone

from src.offers import OfferHistory, OfferIntelligenceService


class OfferIntelligenceServiceTest(unittest.TestCase):

    @patch.dict(os.environ, {"OFFER_SCORE_ENABLED": "False"})
    def test_flag_desativada_mantem_modo_sombra(self):
        service = OfferIntelligenceService(
            logger=logging.getLogger("test.offer_score")
        )
        product = {
            "id": 10,
            "titulo": "Produto atual",
            "loja": "Amazon",
            "preco_valor": 79.90,
            "preco_antigo": 129.90,
            "imagem": "https://example.com/image.jpg",
            "link": "https://example.com/product",
        }

        analysis = service.analyze(product)

        self.assertFalse(analysis.feature_enabled)
        self.assertTrue(analysis.shadow_mode)
        self.assertFalse(analysis.affects_current_flow)
        self.assertIsNotNone(analysis.score)
        self.assertIsNotNone(analysis.filtering)

    @patch.dict(os.environ, {"OFFER_SCORE_ENABLED": "True"})
    def test_flag_ativa_ainda_nao_controla_envio_nesta_fase(self):
        analysis = OfferIntelligenceService().analyze({
            "preco_valor": 10,
        })
        self.assertTrue(analysis.feature_enabled)
        self.assertTrue(analysis.shadow_mode)
        self.assertFalse(analysis.affects_current_flow)

    @patch.dict(os.environ, {"OFFER_SCORE_ENABLED": "False"})
    def test_pipeline_sprint_dois_permanece_analitico(self):
        service = OfferIntelligenceService()
        product = {
            "titulo": "SSD Kingston NV3 1TB",
            "loja": "Amazon",
            "preco_valor": 299.90,
            "preco_antigo": 399.90,
            "categoria_manual": "Tecnologia",
            "imagem": "https://example.com/ssd.jpg",
            "link": "https://example.com/ssd",
        }
        service.remember_for_duplicate_analysis(product)
        analysis = service.analyze(product)
        ranked = service.analyze_batch([product], limit=3)

        self.assertIsNotNone(analysis.identity)
        self.assertIsNotNone(analysis.history)
        self.assertTrue(analysis.duplicate.is_duplicate)
        self.assertEqual(len(ranked), 1)
        self.assertTrue(analysis.shadow_mode)
        self.assertFalse(analysis.affects_current_flow)

    def test_sprint_tres_nao_cria_fila_sem_chamada_explicita(self):
        service = OfferIntelligenceService()
        self.assertFalse(hasattr(service, "queue"))
        self.assertFalse(hasattr(service, "scheduler"))

    def test_historico_temporal_real_alimenta_score(self):
        history = OfferHistory()
        service = OfferIntelligenceService(history=history)
        now = datetime(2026, 7, 26, 12, tzinfo=timezone.utc)
        base = {
            "titulo": "SSD Kingston NV3 1TB",
            "loja": "Amazon",
            "imagem": "https://example.com/ssd.jpg",
            "link": "https://example.com/ssd",
        }
        for days, price in ((2, 100), (1, 95), (0, 80)):
            analysis = service.analyze({
                **base,
                "preco_valor": price,
                "collected_at": now - timedelta(days=days),
            })
        self.assertEqual(analysis.history.observed_days, 3)
        self.assertTrue(analysis.candidate.future_signals[
            "history_reliable_for_score"
        ])
        self.assertEqual(
            analysis.candidate.future_signals["history_trend"], "caiu"
        )
        self.assertGreater(analysis.score.components["price_history"], 0)
        self.assertGreater(analysis.score.components["history_signal"], 0)


if __name__ == "__main__":
    unittest.main()
