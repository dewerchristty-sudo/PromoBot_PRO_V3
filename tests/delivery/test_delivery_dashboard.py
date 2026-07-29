from datetime import datetime, timezone
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from src.core.delivery_models import (
    DeliveryAttempt,
    DeliveryStatus,
    DestinationDelivery,
)
from src.ui.delivery_dashboard import DeliveryDashboard


class DeliveryDashboardTest(unittest.TestCase):

    @staticmethod
    def delivery(
        identifier,
        status,
        *,
        channel="WhatsApp",
        destination="5511999999999",
        error="",
    ):
        now = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)
        return DestinationDelivery(
            id=identifier,
            delivery_key=f"delivery-{identifier}",
            publication_key=f"publication-{identifier}",
            channel=channel,
            destination=destination,
            status=status,
            attempts=1,
            last_error=error,
            created_at=now,
            updated_at=now,
            sent_at=now if status == DeliveryStatus.SENT else None,
        )

    def test_summary_separates_operational_states(self):
        deliveries = [
            self.delivery(1, DeliveryStatus.SENT),
            self.delivery(2, DeliveryStatus.PENDING),
            self.delivery(3, DeliveryStatus.WAITING_RETRY),
            self.delivery(4, DeliveryStatus.DEFINITIVE_FAILURE),
            self.delivery(5, DeliveryStatus.REVIEW_REQUIRED),
        ]
        self.assertEqual(DeliveryDashboard.summary(deliveries), {
            "total": 5,
            "sent": 1,
            "pending": 1,
            "waiting_retry": 1,
            "definitive_failure": 1,
            "review_required": 1,
        })

    def test_filters_by_status_and_channel(self):
        deliveries = [
            self.delivery(1, DeliveryStatus.SENT),
            self.delivery(
                2,
                DeliveryStatus.WAITING_RETRY,
                channel="Telegram",
            ),
            self.delivery(3, DeliveryStatus.WAITING_RETRY),
        ]
        waiting = DeliveryDashboard.filtered(
            deliveries,
            DeliveryStatus.WAITING_RETRY,
        )
        telegram = DeliveryDashboard.filtered(
            deliveries,
            channel="Telegram",
        )
        self.assertEqual([item.id for item in waiting], [2, 3])
        self.assertEqual([item.id for item in telegram], [2])

    def test_delivery_values_mask_destination_and_sensitive_error(self):
        destination = "5511999999999"
        delivery = self.delivery(
            1,
            DeliveryStatus.DEFINITIVE_FAILURE,
            destination=destination,
            error=(
                f"destino={destination} token=segredo "
                "data:image/png;base64,QUJDREVGRw=="
            ),
        )
        values = DeliveryDashboard.delivery_values(delivery)
        rendered = " ".join(str(value) for value in values)
        self.assertIn("***9999", rendered)
        self.assertNotIn(destination, rendered)
        self.assertNotIn("segredo", rendered)
        self.assertNotIn("QUJDREVGRw", rendered)

    def test_attempt_history_is_sanitized_and_ordered(self):
        destination = "5511999999999"
        now = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)
        attempts = [
            DeliveryAttempt(
                id=1,
                delivery_id=1,
                attempt_number=1,
                status=DeliveryStatus.FAILED,
                started_at=now,
                error=f"falha para {destination} password=privada",
            ),
            DeliveryAttempt(
                id=2,
                delivery_id=1,
                attempt_number=2,
                status=DeliveryStatus.SENT,
                started_at=now,
                finished_at=now,
                external_id="mensagem-2",
            ),
        ]
        text = DeliveryDashboard.attempt_history(attempts, destination)
        self.assertLess(text.index("Tentativa 1"), text.index("Tentativa 2"))
        self.assertNotIn(destination, text)
        self.assertNotIn("privada", text)
        self.assertIn("mensagem-2", text)

    def test_panel_has_no_mutating_or_transport_methods(self):
        forbidden = {
            "send",
            "send_alerts",
            "retry",
            "cancel",
            "delete",
            "edit",
            "transition",
            "prepare_manual_retry",
        }
        self.assertFalse(forbidden & set(DeliveryDashboard.__dict__))

    def test_panel_uses_only_repository_read_methods(self):
        source = Path("src/ui/delivery_dashboard.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("self.repository.list(", source)
        self.assertIn("self.repository.attempts_for(", source)
        for forbidden in (
            ".create(",
            ".transition(",
            ".prepare_manual_retry(",
            ".reserve_retry(",
            ".finish_attempt(",
        ):
            self.assertNotIn(forbidden, source)

    def test_main_window_exposes_delivery_dashboard(self):
        source = Path("src/ui/main_window.py").read_text(encoding="utf-8")
        self.assertIn(
            "from src.ui.delivery_dashboard import DeliveryDashboard",
            source,
        )
        self.assertIn('("Entregas", self.mostrar_entregas)', source)
        self.assertIn(
            "lambda: DeliveryDashboard(self.area, self.database)",
            source,
        )

    def test_destroy_closes_owned_repository(self):
        panel = object.__new__(DeliveryDashboard)
        panel.owns_repository = True
        panel.repository = Mock()
        with patch("customtkinter.CTkFrame.destroy"):
            DeliveryDashboard.destroy(panel)
        panel.repository.close.assert_called_once_with()
        self.assertFalse(panel.owns_repository)

    def test_destroy_preserves_injected_repository(self):
        panel = object.__new__(DeliveryDashboard)
        panel.owns_repository = False
        panel.repository = Mock()
        with patch("customtkinter.CTkFrame.destroy"):
            DeliveryDashboard.destroy(panel)
        panel.repository.close.assert_not_called()


if __name__ == "__main__":
    unittest.main()
