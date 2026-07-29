import logging
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from src.core.delivery_models import DeliveryBatchResult, DeliveryStatus
from src.core.delivery_service import DeliveryService
from src.core.notifier import Notifier
from src.core.transactional_canary import (
    TransactionalCanaryConfig,
    normalize_canary_destination,
)
from src.database import Database
from src.database.delivery_repository import DeliveryRepository


class TransactionalCanaryConfigTest(unittest.TestCase):

    def test_defaults_are_safe(self):
        config = TransactionalCanaryConfig.from_environment({})
        self.assertFalse(config.enabled)
        self.assertEqual(config.destinations, frozenset())
        self.assertFalse(config.active(True))

    def test_flag_global_always_wins(self):
        config = TransactionalCanaryConfig(True, frozenset({"5511999999999"}))
        self.assertFalse(config.active(False))
        self.assertTrue(config.active(True))

    def test_normalizes_supported_destinations(self):
        scenarios = {
            "+55 (11) 99999-9999": "5511999999999",
            " 120363000000000000@g.us ": "120363000000000000@g.us",
            "-1001234567890": "1001234567890",
            "123456": "123456",
        }
        for raw, expected in scenarios.items():
            with self.subTest(raw=raw):
                self.assertEqual(normalize_canary_destination(raw), expected)

    def test_list_trims_deduplicates_and_ignores_invalid_values(self):
        diagnostic_logger = Mock(spec=logging.Logger)
        config = TransactionalCanaryConfig.from_environment({
            "ENABLE_TRANSACTIONAL_CANARY": " true ",
            "TRANSACTIONAL_CANARY_DESTINATIONS": (
                " +55 (11) 99999-9999,5511999999999, invalido, ,123 "
            ),
        }, diagnostic_logger)
        self.assertTrue(config.enabled)
        self.assertEqual(config.destinations, frozenset({"5511999999999"}))
        self.assertEqual(diagnostic_logger.warning.call_count, 2)
        logged = " ".join(
            str(call) for call in diagnostic_logger.warning.call_args_list
        )
        self.assertNotIn("invalido", logged)
        self.assertNotIn("5511999999999", logged)

    def test_authorization_is_explicit(self):
        config = TransactionalCanaryConfig(
            True,
            frozenset({"5511999999999", "120363000000000000@g.us"}),
        )
        self.assertTrue(config.authorizes("+55 11 99999-9999"))
        self.assertTrue(config.authorizes("120363000000000000@G.US"))
        self.assertFalse(config.authorizes("5511888888888"))
        self.assertFalse(config.authorizes("destino-invalido"))


class TransactionalCanaryNotifierTest(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "promobot.db"
        self.database = Database(self.path)
        self.repository = DeliveryRepository(self.path)
        self.repository.migrate()
        self.service = DeliveryService(self.repository)
        self.notifier = Notifier(self.database, delivery_service=self.service)
        self.product = {
            "alerta_id": 71,
            "loja": "Shopee",
            "titulo": "Produto canario",
            "preco": "49,90",
            "preco_valor": 49.90,
            "link": "https://example.com/canario",
            "imagem": "https://example.com/canario.jpg",
            "assinatura": "shopee|produto canario",
        }
        self.notifier.whatsapp_configured = Mock(return_value=True)
        self.notifier.evolution_configured = Mock(return_value=False)
        self.notifier.verified_whatsapp_image = Mock(
            return_value=self.product["imagem"]
        )
        self.notifier.whatsapp_group_rate_limited = Mock(return_value=False)
        self.notifier.wait_between_notifications = Mock()

    def tearDown(self):
        self.repository.close()
        self.database.fechar()
        self.tempdir.cleanup()

    @staticmethod
    def flags(destinations="", delivery="true", canary="true", retry="false"):
        return {
            "ENABLE_TRANSACTIONAL_DELIVERY": delivery,
            "ENABLE_TRANSACTIONAL_CANARY": canary,
            "TRANSACTIONAL_CANARY_DESTINATIONS": destinations,
            "ENABLE_TRANSACTIONAL_RETRY": retry,
        }

    def rows(self):
        return self.repository.conn.execute(
            "SELECT * FROM entregas_destino ORDER BY destino"
        ).fetchall()

    def history(self):
        return self.database.listar_historico_envios(50)

    def send_whatsapp(
        self,
        recipients,
        side_effect=None,
        replace_transport=True,
        **flags,
    ):
        self.notifier.whatsapp_recipients_for_alert = Mock(
            return_value=recipients
        )
        if replace_transport:
            self.notifier.send_whatsapp_message = Mock(
                return_value=True,
                side_effect=side_effect,
            )
        with patch.dict(os.environ, self.flags(**flags), clear=False):
            return self.notifier.send_whatsapp_alerts([self.product])

    def test_mixed_destinations_use_exactly_one_route_each(self):
        recipients = ["5511999999999", "5511888888888"]
        result = self.send_whatsapp(
            recipients,
            destinations="5511999999999",
        )
        self.assertIsInstance(result, DeliveryBatchResult)
        self.assertEqual(result.sent_count, 2)
        self.assertEqual(self.notifier.send_whatsapp_message.call_count, 2)
        self.assertEqual([row["destino"] for row in self.rows()], [
            "5511999999999",
        ])
        self.assertEqual(len(self.history()), 2)
        self.assertEqual(
            {item.delivery_key.startswith("legacy:") for item in result.deliveries},
            {False, True},
        )

    def test_empty_or_invalid_list_routes_everything_to_legacy(self):
        for configured in ("", "invalido,123"):
            with self.subTest(configured=configured):
                result = self.send_whatsapp(
                    ["5511888888888"],
                    destinations=configured,
                )
                self.assertEqual(result.sent_count, 1)
                self.assertTrue(result.deliveries[0].delivery_key.startswith(
                    "legacy:"
                ))
        self.assertEqual(len(self.rows()), 0)
        self.assertEqual(len(self.history()), 2)

    def test_canary_flag_off_preserves_existing_all_transactional_flow(self):
        result = self.send_whatsapp(
            ["5511888888888"],
            destinations="5511999999999",
            canary="false",
        )
        self.assertEqual(result.sent_count, 1)
        self.assertFalse(result.deliveries[0].delivery_key.startswith("legacy:"))
        self.assertEqual(len(self.rows()), 1)

    def test_delivery_flag_off_preserves_legacy_and_creates_no_delivery(self):
        result = self.send_whatsapp(
            ["5511999999999"],
            destinations="5511999999999",
            delivery="false",
        )
        self.assertIs(result, True)
        self.assertEqual(len(self.rows()), 0)
        self.assertEqual(len(self.history()), 0)

    def test_authorized_destination_is_idempotent(self):
        with patch.dict(
            os.environ,
            self.flags(destinations="5511999999999"),
            clear=False,
        ):
            self.notifier.whatsapp_recipients_for_alert = Mock(
                return_value=["5511999999999"]
            )
            self.notifier.send_whatsapp_message = Mock(return_value=True)
            first = self.notifier.send_whatsapp_alerts([self.product])
            second = self.notifier.send_whatsapp_alerts([self.product])
        self.assertEqual(first.sent_count, 1)
        self.assertEqual(second.already_sent_count, 1)
        self.assertEqual(self.notifier.send_whatsapp_message.call_count, 1)
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(len(self.history()), 1)

    def test_transactional_failure_does_not_block_legacy_success(self):
        def transport(_message, _image, recipient):
            if recipient == "5511999999999":
                raise RuntimeError(f"falha para {recipient}")
            return True

        result = self.send_whatsapp(
            ["5511999999999", "5511888888888"],
            side_effect=transport,
            destinations="5511999999999",
        )
        self.assertEqual(result.sent_count, 1)
        self.assertEqual(result.failed_count, 1)
        self.assertEqual(self.rows()[0]["status"], DeliveryStatus.FAILED.value)
        self.assertEqual(len(self.history()), 1)
        self.assertNotIn("5511999999999", result.errors[0])

    def test_legacy_failure_does_not_block_transactional_success(self):
        def transport(_message, _image, recipient):
            if recipient == "5511888888888":
                raise RuntimeError(f"falha para {recipient}")
            return True

        result = self.send_whatsapp(
            ["5511999999999", "5511888888888"],
            side_effect=transport,
            destinations="5511999999999",
        )
        self.assertEqual(result.sent_count, 1)
        self.assertEqual(result.failed_count, 1)
        self.assertEqual(self.rows()[0]["status"], DeliveryStatus.SENT.value)
        self.assertEqual(len(self.history()), 1)
        self.assertNotIn("5511888888888", result.errors[0])

    def test_retry_off_leaves_failed_canary_without_new_attempt(self):
        result = self.send_whatsapp(
            ["5511999999999"],
            side_effect=RuntimeError("falha temporaria"),
            destinations="5511999999999",
            retry="false",
        )
        self.assertEqual(result.failed_count, 1)
        row = self.rows()[0]
        self.assertEqual(row["status"], DeliveryStatus.FAILED.value)
        self.assertEqual(row["tentativas"], 1)

    def test_evolution_adapter_receives_same_message_image_and_destination(self):
        self.notifier.evolution_configured = Mock(return_value=True)
        self.product["imagem_whatsapp"] = b"jpeg-validado"
        self.notifier.send_evolution_image = Mock(return_value=True)
        self.notifier.send_whatsapp_message = Mock(
            wraps=self.notifier.send_whatsapp_message
        )
        result = self.send_whatsapp(
            ["5511999999999"],
            destinations="5511999999999",
            replace_transport=False,
        )
        self.assertEqual(result.sent_count, 1)
        message, image, destination = (
            self.notifier.send_evolution_image.call_args.args
        )
        self.assertIn("Produto canario", message)
        self.assertEqual(image, b"jpeg-validado")
        self.assertEqual(destination, "5511999999999")

    def test_telegram_fake_supports_transactional_and_legacy_routes(self):
        self.notifier.send_telegram_photo = Mock(
            return_value={"message_id": "fake-1"}
        )
        with patch.dict(os.environ, {
            **self.flags(destinations="123456"),
            "TELEGRAM_BOT_TOKEN": "token-ficticio",
            "TELEGRAM_CHAT_ID": "123456",
        }, clear=False):
            transactional = self.notifier.send_telegram_alerts([self.product])
        legacy_product = {
            **self.product,
            "alerta_id": 73,
            "link": "https://example.com/telegram-legado",
            "assinatura": "shopee|telegram legado",
        }
        with patch.dict(os.environ, {
            **self.flags(destinations=""),
            "TELEGRAM_BOT_TOKEN": "token-ficticio",
            "TELEGRAM_CHAT_ID": "123456",
        }, clear=False):
            legacy = self.notifier.send_telegram_alerts([legacy_product])
        self.assertEqual(transactional.sent_count, 1)
        self.assertEqual(legacy.sent_count, 1)
        self.assertFalse(transactional.deliveries[0].delivery_key.startswith(
            "legacy:"
        ))
        self.assertTrue(legacy.deliveries[0].delivery_key.startswith("legacy:"))
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(len(self.history()), 2)

    def test_history_failure_after_canary_transport_does_not_repeat_transport(self):
        self.notifier.whatsapp_recipients_for_alert = Mock(
            return_value=["5511999999999"]
        )
        self.notifier.send_whatsapp_message = Mock(return_value=True)
        self.database.registrar_envio = Mock(
            side_effect=RuntimeError("historico indisponivel")
        )
        with patch.dict(
            os.environ,
            self.flags(destinations="5511999999999"),
            clear=False,
        ):
            first = self.notifier.send_whatsapp_alerts([self.product])
            second = self.notifier.send_whatsapp_alerts([self.product])
        self.assertEqual(first.sent_count, 1)
        self.assertTrue(first.history_errors)
        self.assertEqual(second.already_sent_count, 1)
        self.assertEqual(self.notifier.send_whatsapp_message.call_count, 1)

    def test_runtime_rollback_to_legacy_requires_only_flags(self):
        first = self.send_whatsapp(
            ["5511999999999"],
            destinations="5511999999999",
        )
        second_product = {
            **self.product,
            "alerta_id": 72,
            "link": "https://example.com/legado",
            "assinatura": "shopee|legado",
        }
        self.notifier.verified_whatsapp_image.return_value = second_product["imagem"]
        self.notifier.whatsapp_recipients_for_alert.return_value = [
            "5511999999999"
        ]
        with patch.dict(os.environ, self.flags(
            destinations="5511999999999",
            delivery="false",
            canary="false",
        ), clear=False):
            second = self.notifier.send_whatsapp_alerts([second_product])
        self.assertEqual(first.sent_count, 1)
        self.assertIs(second, True)
        self.assertEqual(len(self.rows()), 1)


if __name__ == "__main__":
    unittest.main()
