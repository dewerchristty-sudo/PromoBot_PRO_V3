from pathlib import Path
import tempfile
import unittest

from .scenarios import write_reports


class EnvironmentProtectionTest(unittest.TestCase):

    def test_relatorios_sao_marcados_e_isolados(self):
        with tempfile.TemporaryDirectory(
            prefix="promobot_long_running_reports_"
        ) as directory:
            summary, paths = write_reports(directory)
            combined = "\n".join(
                path.read_text(encoding="utf-8") for path in paths
            )
        self.assertEqual(summary["messages_sent"], 0)
        self.assertIn("SIMULATED_TEST_DATA", combined)
        self.assertNotIn("MLB50957106", combined)
        self.assertNotIn("meli.la", combined)

    def test_suite_nao_importa_transporte_coletor_ou_afiliado(self):
        source = "\n".join(
            path.read_text(encoding="utf-8").casefold()
            for path in (
                Path("tests/long_running/helpers.py"),
                Path("tests/long_running/fixtures.py"),
                Path("tests/long_running/scenarios.py"),
                Path("scripts/run_long_running_tests.py"),
            )
        )
        for forbidden in (
            "src.core.notifier", "src.core.whatsapp",
            "src.affiliates.manager", "scripts.collect_price_history",
            "evolution",
        ):
            self.assertNotIn(forbidden, source)
