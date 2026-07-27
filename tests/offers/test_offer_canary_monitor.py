import os
from unittest.mock import Mock, patch
import unittest

from src.core.monitor import MonitorRunner


class OfferCanaryMonitorIntegrationTest(unittest.TestCase):

    def runner(self):
        runner = MonitorRunner.__new__(MonitorRunner)
        runner.database = Mock()
        runner.notifier = Mock()
        runner.notifier.send_alerts.return_value = "Enviado por: WhatsApp"
        runner.log = Mock()
        return runner

    def test_flag_desligada_chama_notifier_legado_diretamente(self):
        runner = self.runner()
        alerts = [{"titulo": "Produto"}]
        environment = {
            "OFFER_INTELLIGENT_SCHEDULER_ENABLED": "False",
            "OFFER_CANARY_PERCENT": "100",
        }
        with patch.dict(os.environ, environment):
            with patch(
                "src.core.monitor.OfferPipelineRepository"
            ) as repository:
                result = runner.send_automatic_alerts(alerts)
        self.assertEqual(result, "Enviado por: WhatsApp")
        runner.notifier.send_alerts.assert_called_once_with(
            alerts, runner.database
        )
        repository.assert_not_called()

    def test_flag_ativa_passa_pelo_controlador_canary(self):
        runner = self.runner()
        alerts = [{"titulo": "Produto"}]
        repository = Mock()
        controller = Mock()
        controller.execute.return_value = "Enviado por: WhatsApp"
        environment = {
            "OFFER_INTELLIGENT_SCHEDULER_ENABLED": "True",
            "OFFER_CANARY_PERCENT": "10",
        }
        with patch.dict(os.environ, environment):
            with patch(
                "src.core.monitor.OfferPipelineRepository",
                return_value=repository,
            ), patch(
                "src.core.monitor.OfferCanaryController",
                return_value=controller,
            ), patch(
                "src.core.monitor.OfferCanaryAutoStop"
            ) as auto_stop:
                auto_stop.return_value.evaluate.return_value = ""
                result = runner.send_automatic_alerts(alerts)
        self.assertEqual(result, "Enviado por: WhatsApp")
        controller.execute.assert_called_once()
        repository.migrate.assert_called_once()
        repository.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
