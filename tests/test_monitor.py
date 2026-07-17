import unittest
from unittest.mock import Mock

from src.core.monitor import MonitorRunner


class MonitorRunnerTest(unittest.TestCase):

    def test_run_once_notifica_pendentes_antes_de_buscar(self):

        eventos = []
        database = Mock()
        alerts = [
            {
                "alerta_id": 1,
                "link": "https://example.com/produto",
                "loja": "Amazon",
                "titulo": "Produto em oferta",
                "preco_valor": 99.9,
            }
        ]
        database.alertas_pendentes.side_effect = [alerts, []]
        database.listar_monitoramentos.return_value = [
            {
                "id": 1,
                "termo": "oferta",
                "lojas": "Amazon",
            }
        ]

        runner = MonitorRunner(database)
        runner.notifier = Mock()
        runner.notifier.send_alerts.side_effect = lambda *_: eventos.append(
            "notificou"
        ) or "Enviado por: WhatsApp"
        runner.execute_monitoring = Mock(
            side_effect=lambda *_: eventos.append("buscou") or 1
        )

        total = runner.run_once()

        self.assertEqual(total, 1)
        self.assertEqual(eventos[0], "notificou")
        self.assertEqual(eventos[1], "buscou")


if __name__ == "__main__":
    unittest.main()
