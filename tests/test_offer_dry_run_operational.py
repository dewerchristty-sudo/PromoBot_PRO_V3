from pathlib import Path
import json
import tempfile
import unittest

from scripts.run_offer_dry_run import TEMPORARY_FLAGS, write_reports


class OfferDryRunOperationalTest(unittest.TestCase):

    def test_configuracao_e_estritamente_simulada(self):
        self.assertEqual(
            TEMPORARY_FLAGS["OFFER_INTELLIGENT_SCHEDULER_ENABLED"], "True"
        )
        self.assertEqual(TEMPORARY_FLAGS["OFFER_CANARY_PERCENT"], "5")
        self.assertEqual(TEMPORARY_FLAGS["OFFER_MIN_SCORE_TO_SEND"], "90")
        self.assertEqual(TEMPORARY_FLAGS["OFFER_MAX_SEND_PER_HOUR"], "1")
        self.assertEqual(TEMPORARY_FLAGS["OFFER_MAX_SEND_PER_DAY"], "3")
        self.assertEqual(TEMPORARY_FLAGS["OFFER_DRY_RUN_TRANSPORT"], "True")

    def test_executor_nao_importa_notifier_nem_transportes(self):
        source = Path("scripts/run_offer_dry_run.py").read_text(
            encoding="utf-8"
        ).casefold()
        for forbidden in (
            "from src.core.notifier", "send_whatsapp",
            "send_telegram", "send_evolution", "send_webhook",
        ):
            self.assertNotIn(forbidden, source)

    def test_exporta_json_csv_e_resumo(self):
        row = {
            "loja": "Mercado Livre", "titulo": "SSD",
            "score": 95.0, "resultado_final": "SERIA ENVIADA",
        }
        report = {
            "executed_at": "2026-07-26T12:00:00+00:00",
            "query": "ssd 1tb",
            "metrics": {
                "collected": 1, "analyzed": 1, "discarded": 0,
                "duplicates": 0, "blocked": 0, "approved": 1,
                "excellent": 1, "good": 0, "queued": 1,
                "selected": 1, "rejected": 0, "average_score": 95,
            },
            "stores": {
                "Mercado Livre": {
                    "collected": 1, "seconds": 1.0, "error": ""
                }
            },
            "safety": {
                "transport_called": False, "auto_stop": "nenhum"
            },
            "performance": {
                "total_seconds": 1.0, "peak_memory_mb": 2.0
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            files = write_reports(report, [row], Path(directory))
            self.assertEqual(len(files), 3)
            self.assertEqual(
                json.loads(Path(files[0]).read_text(
                    encoding="utf-8"
                ))["metrics"]["selected"],
                1,
            )
            self.assertIn(
                "SERIA ENVIADA",
                Path(files[1]).read_text(encoding="utf-8-sig"),
            )
            self.assertIn(
                "Dry Run".casefold(),
                Path(files[2]).read_text(encoding="utf-8").casefold(),
            )


if __name__ == "__main__":
    unittest.main()
