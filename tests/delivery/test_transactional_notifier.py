import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from src.core.delivery_models import DeliveryBatchResult, DeliveryStatus
from src.core.delivery_models import DestinationDelivery
from src.core.delivery_service import DeliveryService
from src.core.notifier import Notifier
from src.database import Database
from src.database.delivery_repository import DeliveryRepository


class TransactionalNotifierTest(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "promobot.db"
        self.database = Database(self.path)
        self.repository = DeliveryRepository(self.path)
        self.repository.migrate()
        self.service = DeliveryService(self.repository)
        self.notifier = Notifier(
            self.database,
            delivery_service=self.service,
        )
        self.product = {
            "alerta_id": 7,
            "loja": "Shopee",
            "titulo": "Produto transacional",
            "preco": "49,90",
            "preco_valor": 49.90,
            "link": "https://example.com/produto",
            "imagem": "https://example.com/produto.jpg",
            "assinatura": "shopee|produto transacional",
        }

    def tearDown(self):
        self.repository.close()
        self.database.fechar()
        self.tempdir.cleanup()

    def configure_whatsapp(self, recipients):
        self.notifier.whatsapp_configured = Mock(return_value=True)
        self.notifier.evolution_configured = Mock(return_value=False)
        self.notifier.verified_whatsapp_image = Mock(
            return_value=self.product["imagem"]
        )
        self.notifier.whatsapp_recipients_for_alert = Mock(
            return_value=list(recipients)
        )
        self.notifier.whatsapp_group_rate_limited = Mock(return_value=False)
        self.notifier.wait_between_notifications = Mock()

    def delivery_rows(self):
        return self.repository.conn.execute("""
            SELECT * FROM entregas_destino ORDER BY destino
        """).fetchall()

    def history_rows(self):
        return self.database.listar_historico_envios(50)

    def test_flag_desligada_mantem_caminho_legado_sem_criar_entregas(self):
        self.configure_whatsapp(["5511999999999"])
        self.notifier.send_whatsapp_message = Mock(return_value=True)
        with patch.dict(
            os.environ,
            {"ENABLE_TRANSACTIONAL_DELIVERY": "false"},
        ):
            result = self.notifier.send_whatsapp_alerts([self.product])
        self.assertIs(result, True)
        self.assertEqual(self.notifier.send_whatsapp_message.call_count, 1)
        self.assertEqual(len(self.delivery_rows()), 0)
        self.assertEqual(len(self.history_rows()), 0)

    def test_flag_desligada_nao_instancia_delivery_repository(self):
        notifier = Notifier(self.database)
        notifier.whatsapp_configured = Mock(return_value=True)
        notifier.verified_whatsapp_image = Mock(
            return_value=self.product["imagem"]
        )
        notifier.evolution_configured = Mock(return_value=False)
        notifier.whatsapp_recipients_for_alert = Mock(
            return_value=["5511999999999"]
        )
        notifier.whatsapp_group_rate_limited = Mock(return_value=False)
        notifier.send_whatsapp_message = Mock(return_value=True)
        with patch(
            "src.core.notifier.DeliveryRepository"
        ) as repository_class, patch.dict(
            os.environ,
            {"ENABLE_TRANSACTIONAL_DELIVERY": "false"},
        ):
            result = notifier.send_whatsapp_alerts([self.product])
        self.assertIs(result, True)
        repository_class.assert_not_called()

    def test_falha_na_migracao_fecha_repositorio_interno(self):
        notifier = Notifier(self.database)
        repository = Mock()
        repository.migrate.side_effect = RuntimeError("migracao indisponivel")
        with patch(
            "src.core.notifier.DeliveryRepository",
            return_value=repository,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "migracao indisponivel",
            ):
                notifier.transactional_delivery_service()
        repository.close.assert_called_once_with()
        self.assertIsNone(notifier._delivery_repository)

    def test_sucesso_em_todos_os_destinos_e_registrado_individualmente(self):
        recipients = ["5511999999999", "5511888888888"]
        self.configure_whatsapp(recipients)
        self.notifier.send_whatsapp_message = Mock(return_value=True)
        with patch.dict(
            os.environ,
            {"ENABLE_TRANSACTIONAL_DELIVERY": "true"},
        ):
            result = self.notifier.send_whatsapp_alerts([self.product])
        self.assertIsInstance(result, DeliveryBatchResult)
        self.assertEqual(result.sent_count, 2)
        self.assertEqual(result.failed_count, 0)
        self.assertEqual(
            {row["status"] for row in self.delivery_rows()},
            {DeliveryStatus.SENT.value},
        )
        self.assertEqual(len(self.repository.attempts_for(
            self.delivery_rows()[0]["id"]
        )), 1)
        self.assertEqual(len(self.history_rows()), 2)

    def test_falha_parcial_preserva_sucesso_e_isola_destino(self):
        recipients = ["5511999999999", "5511888888888"]
        self.configure_whatsapp(recipients)

        def send(_message, _image, recipient):
            if recipient == "5511888888888":
                raise RuntimeError(
                    f"falha simulada para {recipient}"
                )
            return True

        self.notifier.send_whatsapp_message = Mock(side_effect=send)
        with patch.dict(
            os.environ,
            {"ENABLE_TRANSACTIONAL_DELIVERY": "true"},
        ):
            result = self.notifier.send_whatsapp_alerts([self.product])
        self.assertEqual(result.sent_count, 1)
        self.assertEqual(result.failed_count, 1)
        self.assertEqual(
            {row["status"] for row in self.delivery_rows()},
            {DeliveryStatus.SENT.value, DeliveryStatus.FAILED.value},
        )
        self.assertEqual(len(self.history_rows()), 1)
        failed = next(
            row for row in self.delivery_rows()
            if row["status"] == DeliveryStatus.FAILED.value
        )
        self.assertNotIn("5511888888888", failed["ultimo_erro"])
        self.assertIn("***8888", failed["ultimo_erro"])

    def test_destino_enviado_nao_recebe_novamente(self):
        self.configure_whatsapp(["5511999999999"])
        self.notifier.send_whatsapp_message = Mock(return_value=True)
        with patch.dict(
            os.environ,
            {"ENABLE_TRANSACTIONAL_DELIVERY": "true"},
        ):
            first = self.notifier.send_whatsapp_alerts([self.product])
            second = self.notifier.send_whatsapp_alerts([self.product])
        self.assertEqual(first.sent_count, 1)
        self.assertEqual(second.sent_count, 0)
        self.assertEqual(second.already_sent_count, 1)
        self.assertEqual(self.notifier.send_whatsapp_message.call_count, 1)
        self.assertEqual(len(self.history_rows()), 1)
        self.assertEqual(len(self.delivery_rows()), 1)

    def test_chave_persiste_entre_instancias_independentes(self):
        self.configure_whatsapp(["5511999999999"])
        self.notifier.send_whatsapp_message = Mock(return_value=True)
        with patch.dict(
            os.environ,
            {"ENABLE_TRANSACTIONAL_DELIVERY": "true"},
        ):
            first = self.notifier.send_whatsapp_alerts([self.product])
        first_key = first.deliveries[0].delivery_key

        second_notifier = Notifier(self.database)
        second_notifier.whatsapp_configured = Mock(return_value=True)
        second_notifier.evolution_configured = Mock(return_value=False)
        second_notifier.verified_whatsapp_image = Mock(
            return_value=self.product["imagem"]
        )
        second_notifier.whatsapp_recipients_for_alert = Mock(
            return_value=["5511999999999"]
        )
        second_notifier.whatsapp_group_rate_limited = Mock(return_value=False)
        second_notifier.send_whatsapp_message = Mock(return_value=True)
        with patch.dict(
            os.environ,
            {"ENABLE_TRANSACTIONAL_DELIVERY": "true"},
        ):
            second = second_notifier.send_whatsapp_alerts([self.product])

        self.assertEqual(second.deliveries[0].delivery_key, first_key)
        self.assertEqual(second.already_sent_count, 1)
        second_notifier.send_whatsapp_message.assert_not_called()
        self.assertIsNone(second_notifier._delivery_repository)

    def test_destino_com_falha_nao_e_retentado_nesta_etapa(self):
        self.configure_whatsapp(["5511999999999"])
        self.notifier.send_whatsapp_message = Mock(
            side_effect=RuntimeError("indisponivel")
        )
        with patch.dict(
            os.environ,
            {"ENABLE_TRANSACTIONAL_DELIVERY": "true"},
        ):
            first = self.notifier.send_whatsapp_alerts([self.product])
            second = self.notifier.send_whatsapp_alerts([self.product])
        self.assertEqual(first.failed_count, 1)
        self.assertEqual(second.failed_count, 1)
        self.assertEqual(self.notifier.send_whatsapp_message.call_count, 1)
        self.assertEqual(
            self.delivery_rows()[0]["status"],
            DeliveryStatus.FAILED.value,
        )

    def test_estados_terminais_e_revisao_nao_sao_enviados(self):
        for status in (
            DeliveryStatus.SENT,
            DeliveryStatus.REVIEW_REQUIRED,
            DeliveryStatus.DEFINITIVE_FAILURE,
        ):
            with self.subTest(status=status):
                delivery = DestinationDelivery.create(
                    f"publicacao-{status.value}",
                    "WhatsApp",
                    "5511999999999",
                    status=status,
                )
                stored, _ = self.repository.create(delivery)
                transport = Mock(return_value=True)
                result = self.service.deliver(stored, transport)
                transport.assert_not_called()
                self.assertEqual(result.status, status)

    def test_publicacoes_e_destinos_permanecem_isolados(self):
        self.configure_whatsapp(["5511999999999"])
        self.notifier.send_whatsapp_message = Mock(return_value=True)
        second_product = {
            **self.product,
            "alerta_id": 8,
            "link": "https://example.com/outro",
            "assinatura": "shopee|outro produto",
        }
        with patch.dict(
            os.environ,
            {"ENABLE_TRANSACTIONAL_DELIVERY": "true"},
        ):
            result = self.notifier.send_whatsapp_alerts([
                self.product,
                second_product,
            ])
        self.assertEqual(result.sent_count, 2)
        self.assertEqual(len(self.delivery_rows()), 2)
        self.assertEqual(len({
            row["chave_entrega"] for row in self.delivery_rows()
        }), 2)

    def test_telegram_reutiliza_transporte_e_registra_id_externo(self):
        self.notifier.send_telegram_photo = Mock(
            return_value={"message_id": "telegram-123"}
        )
        with patch.dict(os.environ, {
            "ENABLE_TRANSACTIONAL_DELIVERY": "true",
            "TELEGRAM_BOT_TOKEN": "token-de-teste",
            "TELEGRAM_CHAT_ID": "123456",
        }):
            result = self.notifier.send_telegram_alerts([self.product])
        self.assertEqual(result.sent_count, 1)
        self.assertEqual(
            result.deliveries[0].external_id,
            "telegram-123",
        )
        self.assertEqual(len(self.history_rows()), 1)
        self.assertEqual(self.history_rows()[0]["canal"], "Telegram")

    def test_evolution_continua_sendo_chamada_pelo_adaptador_existente(self):
        self.configure_whatsapp(["5511999999999"])
        self.notifier.evolution_configured = Mock(return_value=True)
        self.notifier.verified_whatsapp_image = Mock(
            return_value=self.product["imagem"]
        )
        self.product["imagem_whatsapp"] = b"imagem-jpeg-validada"
        self.notifier.send_evolution_image = Mock(return_value=True)
        with patch.dict(
            os.environ,
            {"ENABLE_TRANSACTIONAL_DELIVERY": "true"},
        ):
            result = self.notifier.send_whatsapp_alerts([self.product])
        self.assertEqual(result.sent_count, 1)
        self.notifier.send_evolution_image.assert_called_once()
        message, image, destination = (
            self.notifier.send_evolution_image.call_args.args
        )
        self.assertIn("Produto transacional", message)
        self.assertEqual(image, b"imagem-jpeg-validada")
        self.assertEqual(destination, "5511999999999")

    def test_falha_no_historico_nao_reenvia_transporte_confirmado(self):
        self.configure_whatsapp(["5511999999999"])
        self.notifier.send_whatsapp_message = Mock(return_value=True)
        self.database.registrar_envio = Mock(
            side_effect=RuntimeError("historico indisponivel")
        )
        with patch.dict(
            os.environ,
            {"ENABLE_TRANSACTIONAL_DELIVERY": "true"},
        ):
            first = self.notifier.send_whatsapp_alerts([self.product])
            second = self.notifier.send_whatsapp_alerts([self.product])
        self.assertEqual(first.sent_count, 1)
        self.assertTrue(first.history_errors)
        self.assertEqual(second.already_sent_count, 1)
        self.assertEqual(self.notifier.send_whatsapp_message.call_count, 1)
        self.database.registrar_envio = Mock(
            wraps=Database.registrar_envio.__get__(
                self.database,
                Database,
            )
        )
        self.notifier.record_single_delivery(
            self.database,
            self.product,
            "WhatsApp",
            "5511999999999",
        )
        with patch.dict(
            os.environ,
            {"ENABLE_TRANSACTIONAL_DELIVERY": "true"},
        ):
            third = self.notifier.send_whatsapp_alerts([self.product])
        self.assertEqual(third.already_sent_count, 1)
        self.assertEqual(len(self.history_rows()), 1)

    def test_send_alerts_consolida_sucesso_parcial_sem_apagar_falha(self):
        recipients = ["5511999999999", "5511888888888"]
        self.configure_whatsapp(recipients)
        self.notifier.send_telegram_alerts = Mock(return_value=False)
        self.notifier.partition_enabled_stores = Mock(
            return_value=([self.product], [])
        )
        self.notifier.partition_offer_quality = Mock(
            return_value=([self.product], [], [])
        )
        self.notifier.partition_affiliate_ready = Mock(
            return_value=([self.product], [])
        )
        self.notifier.partition_image_ready = Mock(
            return_value=([self.product], [])
        )
        self.notifier.partition_whatsapp_routable = Mock(
            return_value=([self.product], [])
        )
        self.notifier.apply_hourly_limit = Mock(
            return_value=([self.product], [])
        )
        self.notifier.record_review_pendencies = Mock()

        def send(_message, _image, recipient):
            if recipient == "5511888888888":
                raise RuntimeError("falha simulada")
            return True

        self.notifier.send_whatsapp_message = Mock(side_effect=send)
        with patch.dict(
            os.environ,
            {"ENABLE_TRANSACTIONAL_DELIVERY": "true"},
        ):
            result = self.notifier.send_alerts(
                [self.product],
                self.database,
                ignore_notification_hours=True,
            )
        self.assertTrue(result.startswith("Enviado por: WhatsApp"))
        self.assertIn("1 falha(s) isolada(s) por destino", result)
        self.assertEqual(len(self.delivery_rows()), 2)
        self.assertEqual(len(self.history_rows()), 1)
        sent_markers = self.database.conn.execute(
            "SELECT COUNT(*) FROM notificacoes_enviadas"
        ).fetchone()[0]
        self.assertEqual(sent_markers, 1)


if __name__ == "__main__":
    unittest.main()
