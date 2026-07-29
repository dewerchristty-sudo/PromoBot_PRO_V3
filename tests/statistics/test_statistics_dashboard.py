from datetime import datetime, timezone
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from src.statistics.models import (
    CoverageAverage,
    CoverageCount,
    GroupCount,
    StatisticsSnapshot,
)
from src.ui.statistics_dashboard import StatisticsDashboard


class TextWidget:

    def __init__(self):
        self.value = ""

    def delete(self, *_args):
        self.value = ""

    def insert(self, _position, value):
        self.value += value


class StatisticsDashboardTest(unittest.TestCase):

    def test_coverage_text_always_exposes_numerator_and_denominator(self):
        panel = object.__new__(StatisticsDashboard)
        panel.coverage_summary = TextWidget()
        snapshot = StatisticsSnapshot(
            products_by_category=CoverageCount(
                items=(GroupCount("Casa", 2),),
                covered=2,
                total=10,
            ),
            sent_categories=CoverageCount(covered=1, total=4),
            average_discount=CoverageAverage(
                average=25,
                covered=2,
                total=10,
            ),
            average_savings=CoverageAverage(
                average=30,
                covered=2,
                total=10,
            ),
            generated_at=datetime(2026, 7, 29, tzinfo=timezone.utc),
        )
        panel.fill_coverage(snapshot)
        self.assertIn("2 de 10 produtos", panel.coverage_summary.value)
        self.assertIn("1 de 4 envios", panel.coverage_summary.value)
        self.assertIn("média: 25.0%", panel.coverage_summary.value)
        self.assertIn("média: R$ 30.00", panel.coverage_summary.value)

    def test_group_rendering_handles_empty_database(self):
        widget = TextWidget()
        StatisticsDashboard.fill_groups(widget, ())
        self.assertEqual(widget.value, "Nenhum dado disponível.")

    def test_panel_has_no_mutating_or_transport_methods(self):
        forbidden = {
            "send",
            "retry",
            "delete",
            "edit",
            "transition",
            "cancel",
            "save",
        }
        self.assertFalse(forbidden & set(StatisticsDashboard.__dict__))

    def test_repository_source_is_read_only_and_uses_mode_ro(self):
        source = Path("src/statistics/repository.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("?mode=ro", source)
        for forbidden in (
            "INSERT INTO",
            "UPDATE ",
            "DELETE FROM",
            "CREATE TABLE",
            "ALTER TABLE",
            "DROP TABLE",
        ):
            self.assertNotIn(forbidden, source)

    def test_dashboard_does_not_render_sensitive_delivery_fields(self):
        source = Path("src/ui/statistics_dashboard.py").read_text(
            encoding="utf-8"
        )
        for forbidden in (
            "destino",
            "link_afiliado",
            "payload",
            "base64",
            "token",
            "cookie",
        ):
            self.assertNotIn(forbidden, source.casefold())

    def test_main_window_exposes_statistics_dashboard(self):
        source = Path("src/ui/main_window.py").read_text(encoding="utf-8")
        self.assertIn(
            "from src.ui.statistics_dashboard import StatisticsDashboard",
            source,
        )
        self.assertIn(
            '("Estatísticas", self.mostrar_estatisticas)',
            source,
        )
        self.assertIn(
            "lambda: StatisticsDashboard(self.area, self.database)",
            source,
        )

    def test_destroy_closes_owned_repository(self):
        panel = object.__new__(StatisticsDashboard)
        panel.owns_repository = True
        panel.repository = Mock()
        with patch("customtkinter.CTkFrame.destroy"):
            StatisticsDashboard.destroy(panel)
        panel.repository.close.assert_called_once_with()
        self.assertFalse(panel.owns_repository)

    def test_destroy_preserves_injected_repository(self):
        panel = object.__new__(StatisticsDashboard)
        panel.owns_repository = False
        panel.repository = Mock()
        with patch("customtkinter.CTkFrame.destroy"):
            StatisticsDashboard.destroy(panel)
        panel.repository.close.assert_not_called()


if __name__ == "__main__":
    unittest.main()
