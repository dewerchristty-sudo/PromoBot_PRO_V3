from datetime import datetime, timezone
from unittest.mock import Mock

from src.statistics.models import GroupCount, StatisticsSnapshot
from src.ui.hunter_statistics_panel import HunterStatisticsPanel


def snapshot(total=2):
    return StatisticsSnapshot(
        total_products=total,
        total_sends=1,
        products_by_store=(GroupCount("Amazon", 2),),
        generated_at=datetime.now(timezone.utc),
    )


def test_summary_is_default_and_panel_has_all_operational_tabs():
    panel = object.__new__(HunterStatisticsPanel)
    panel.selected_tab = "Resumo"
    assert panel.selected_tab == "Resumo"
    assert HunterStatisticsPanel.TABS == (
        "Resumo", "Lojas", "Categorias", "Produtos", "Envios",
        "Evolução", "Erros", "Últimos envios", "Atividade", "Monitores",
        "Diagnóstico de entrega",
    )


def test_each_tab_builds_only_its_own_content():
    value = snapshot()
    assert HunterStatisticsPanel.content_lines("Lojas", value) == ["Amazon: 2"]
    summary = HunterStatisticsPanel.content_lines("Resumo", value)
    assert any("Produtos encontrados: 2" in line for line in summary)
    assert "Amazon: 2" not in summary


def test_unchanged_snapshot_does_not_render_again():
    panel = object.__new__(HunterStatisticsPanel)
    panel.expanded = True
    panel.repository = Mock()
    panel.repository.snapshot.side_effect = [snapshot(), snapshot()]
    panel.snapshot_signature = None
    panel.snapshot = None
    panel.rendered_signatures = {}
    panel.render_selected = Mock()
    assert panel.refresh()
    assert not panel.refresh()
    panel.render_selected.assert_called_once()


def test_collapsed_panel_does_not_query_or_render():
    panel = object.__new__(HunterStatisticsPanel)
    panel.expanded = False
    panel.repository = Mock()
    assert not panel.refresh()
    panel.repository.snapshot.assert_not_called()


def test_panel_defines_no_timer():
    assert "after" not in HunterStatisticsPanel.__dict__


def test_switching_pages_reuses_existing_frames():
    panel = object.__new__(HunterStatisticsPanel)
    panel.selected_tab = "Resumo"
    panel.snapshot = snapshot()
    panel.snapshot_signature = HunterStatisticsPanel.signature(panel.snapshot)
    panel.rendered_signatures = {}
    summary_page = Mock()
    stores_page = Mock()
    panel.pages = {"Resumo": summary_page, "Lojas": stores_page}
    panel.buttons = {}
    panel._highlight = Mock()
    panel.render_selected = Mock()

    panel.select("Lojas")

    summary_page.pack_forget.assert_called_once()
    stores_page.pack.assert_called_once_with(fill="both", expand=True)
    assert panel.pages["Resumo"] is summary_page
    assert panel.pages["Lojas"] is stores_page


def test_only_selected_page_is_rendered_after_snapshot_change():
    panel = object.__new__(HunterStatisticsPanel)
    panel.selected_tab = "Resumo"
    panel.snapshot = snapshot()
    panel.snapshot_signature = HunterStatisticsPanel.signature(panel.snapshot)
    panel.rendered_signatures = {}
    widget = Mock()
    panel.page_widgets = {"Resumo": widget, "Lojas": Mock()}

    assert panel.render_selected()
    widget.insert.assert_called_once()
    panel.page_widgets["Lojas"].insert.assert_not_called()


def test_activity_page_is_navigation_only_and_uses_external_component():
    panel = object.__new__(HunterStatisticsPanel)
    panel.selected_tab = "Atividade"
    panel.snapshot = snapshot()
    panel.snapshot_signature = HunterStatisticsPanel.signature(panel.snapshot)
    panel.rendered_signatures = {}
    panel.page_widgets = {}

    assert not panel.render_selected()


def test_monitors_page_is_navigation_only_and_uses_existing_cards():
    panel = object.__new__(HunterStatisticsPanel)
    panel.selected_tab = "Monitores"
    panel.snapshot = snapshot()
    panel.snapshot_signature = HunterStatisticsPanel.signature(panel.snapshot)
    panel.rendered_signatures = {}
    panel.page_widgets = {}

    assert not panel.render_selected()
