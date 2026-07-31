from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from src.ui.monitor_page import MonitorPage, MonitorStatusPresenter


def monitor(
    identifier=57,
    active=1,
    last="2026-07-30 00:54:55",
    total=18,
):
    return {
        "id": identifier,
        "termo": "shampoo wella",
        "lojas": "Mercado Livre",
        "intervalo_minutos": 30,
        "ativo": active,
        "ultima_execucao": last,
        "ultimo_total": total,
    }


def test_summary_reflects_real_runner_state_and_counts():
    monitors = [monitor(), monitor(58, active=0)]
    telemetry = {
        57: {"status": "failed"},
        58: {"status": "success"},
    }
    summary = MonitorStatusPresenter.summary(
        monitors,
        {
            "automatic_running": True,
            "current_monitor_id": 57,
            "current_monitor_term": "shampoo wella",
        },
        telemetry,
    )
    assert summary == {
        "automatic_running": True,
        "active": 1,
        "paused": 1,
        "running": 1,
        "errors": 1,
        "current_id": 57,
        "current_term": "shampoo wella",
    }


def test_summary_shows_automatic_stopped_and_nobody_running():
    summary = MonitorStatusPresenter.summary(
        [], {"automatic_running": False}, {}
    )
    assert not summary["automatic_running"]
    assert summary["running"] == 0
    assert summary["current_id"] is None


def test_active_and_paused_visual_status_and_action():
    presenter = MonitorStatusPresenter()
    assert presenter.configuration_status(monitor()) == "🟢 ATIVO"
    assert presenter.action_text(monitor()) == "Pausar"
    assert presenter.configuration_status(monitor(active=0)) == "⚪ PAUSADO"
    assert presenter.action_text(monitor(active=0)) == "Ativar"


def test_error_does_not_change_active_configuration():
    presenter = MonitorStatusPresenter()
    result, error = presenter.last_result({
        "status": "failed",
        "errors": ("HTTP 503",),
    })
    assert presenter.configuration_status(monitor()) == "🟢 ATIVO"
    assert result == "🔴 ERRO"
    assert error == "HTTP 503"


def test_dates_use_brazilian_format():
    assert (
        MonitorStatusPresenter.format_datetime("2026-07-30 00:54:55")
        == "30/07/2026 às 00:54:55"
    )


def test_compact_date_format():
    assert (
        MonitorStatusPresenter.format_compact_datetime(
            "2026-07-30 00:54:55"
        )
        == "30/07 00:54"
    )


def test_active_next_execution_and_visual_minutes():
    now = datetime(2026, 7, 30, 1, 10, 0)
    expected, remaining = MonitorStatusPresenter.next_execution(
        monitor(), now
    )
    assert expected == "30/07/2026 às 01:24:55"
    assert remaining == 15


def test_active_next_execution_is_presented_as_forecast():
    expected, remaining = MonitorStatusPresenter.next_execution(
        monitor(), datetime(2026, 7, 30, 1, 10, 0)
    )
    visual = f"a partir de {expected}" if remaining is not None else expected
    assert visual == "a partir de 30/07/2026 às 01:24:55"


def test_paused_has_no_next_execution():
    assert MonitorStatusPresenter.next_execution(
        monitor(active=0)
    ) == ("—", None)


def test_never_executed_has_first_execution_messages():
    item = monitor(last=None)
    assert (
        MonitorStatusPresenter.format_datetime(item["ultima_execucao"])
        == "Ainda não executado"
    )
    assert MonitorStatusPresenter.next_execution(item) == (
        "Aguardando primeira execução",
        None,
    )


def test_toggle_card_uses_exact_monitor_id():
    page = object.__new__(MonitorPage)
    page.database = Mock()
    page.carregar = Mock()
    page.toggle_monitor(57)
    page.database.alternar_monitoramento.assert_called_once_with(57)
    page.carregar.assert_called_once()


def test_remove_requires_confirmation_and_uses_exact_id():
    page = object.__new__(MonitorPage)
    page.database = Mock()
    page.carregar = Mock()
    with patch(
        "src.ui.monitor_page.messagebox.askyesno",
        return_value=False,
    ):
        page.remove_monitor(monitor())
    page.database.remover_monitoramento.assert_not_called()

    with patch(
        "src.ui.monitor_page.messagebox.askyesno",
        return_value=True,
    ):
        page.remove_monitor(monitor())
    page.database.remover_monitoramento.assert_called_once_with(57)


def test_card_execution_rejects_second_click_without_starting_thread():
    page = object.__new__(MonitorPage)
    page.manual_monitor_ids = {57}
    page.runner = Mock()
    page.runner.execution_lock.locked.return_value = False
    with patch("src.ui.monitor_page.messagebox.showinfo") as show:
        page.execute_card(monitor())
    show.assert_called_once()


def test_card_execution_uses_only_selected_monitor():
    page = object.__new__(MonitorPage)
    page.runner = Mock()
    page.runner.run_monitor_once.return_value = 3
    page.after = lambda _delay, callback: callback()
    page.append_activity = Mock()
    page._finish_card_execution = Mock()
    selected = monitor(57)
    page._execute_card_thread(selected)
    page.runner.run_monitor_once.assert_called_once_with(selected)
    page.runner.run_once.assert_not_called()


def test_missing_id_has_clear_message_and_does_not_toggle():
    page = object.__new__(MonitorPage)
    page.id_entry = Mock()
    page.id_entry.get.return_value = "999"
    page.monitoramentos = [monitor(57)]
    page.database = Mock()
    with patch("src.ui.monitor_page.messagebox.showerror") as show:
        page.alternar()
    show.assert_called_once()
    assert "999" in show.call_args.args[1]
    page.database.alternar_monitoramento.assert_not_called()


def test_general_execution_preserves_run_once_contract():
    page = object.__new__(MonitorPage)
    page.runner = Mock()
    page.runner.run_once.return_value = 9
    page.after = lambda _delay, callback: callback()
    page.append_activity = Mock()
    page._finish_general_execution = Mock()
    page._executar_agora_thread()
    page.runner.run_once.assert_called_once_with()


def test_refresh_only_reads_state_and_never_starts_collection():
    page = object.__new__(MonitorPage)
    page.database = Mock()
    page.database.listar_monitoramentos.return_value = []
    page.runner = Mock()
    page.runner.status_snapshot.return_value = {}
    page.presenter = MonitorStatusPresenter()
    page.monitoramentos = []
    page.telemetry_by_id = {}
    page.manual_monitor_ids = set()
    page.expanded_monitor_ids = set()
    page.previous_visual_snapshot = None
    page.previous_cards_snapshot = None
    page.render_summary = Mock()
    page.render_cards = Mock()
    page.get_scroll_position = Mock(return_value=0)
    page.restore_scroll_position = Mock()
    page.update_countdown_labels = Mock()
    page.update_id_action = Mock()
    page.carregar()
    page.runner.run_once.assert_not_called()
    page.runner.run_monitor_once.assert_not_called()


def make_refresh_page(monitors=None):
    page = object.__new__(MonitorPage)
    page.database = Mock()
    page.database.listar_monitoramentos.return_value = monitors or []
    page.runner = Mock()
    page.runner.status_snapshot.return_value = {
        "automatic_running": False,
    }
    page.presenter = MonitorStatusPresenter()
    page.monitoramentos = []
    page.telemetry_by_id = {}
    page.manual_monitor_ids = set()
    page.expanded_monitor_ids = set()
    page.previous_visual_snapshot = None
    page.previous_cards_snapshot = None
    page.telemetry_for = Mock(return_value=None)
    page.render_summary = Mock()
    page.render_cards = Mock()
    page.update_id_action = Mock()
    page.update_countdown_labels = Mock()
    page.update_updated_time = Mock()
    page.get_scroll_position = Mock(return_value=0.42)
    page.restore_scroll_position = Mock()
    return page


def test_refresh_without_change_does_not_recreate_cards():
    page = make_refresh_page([monitor()])
    page.carregar()
    page.carregar()
    page.render_cards.assert_called_once()
    page.update_countdown_labels.assert_called_once()


def test_scroll_position_is_preserved_when_cards_change():
    page = make_refresh_page([monitor()])
    page.carregar()
    page.restore_scroll_position.assert_called_once_with(0.42)


def test_expanded_monitor_is_part_of_visual_snapshot():
    page = make_refresh_page([monitor()])
    first = page.build_cards_snapshot(
        [monitor()], {}, {57: None}
    )
    page.expanded_monitor_ids.add(57)
    second = page.build_cards_snapshot(
        [monitor()], {}, {57: None}
    )
    assert first != second
    assert 57 in page.expanded_monitor_ids


def test_collapsed_activity_accumulates_without_rebuilding_widget():
    page = object.__new__(MonitorPage)
    page.activity_expanded = False
    page.activity_lines = []
    page.activity = Mock()
    page.append_activity("Evento real")
    assert len(page.activity_lines) == 1
    page.activity.delete.assert_not_called()
    page.activity.insert.assert_not_called()


def test_opening_activity_shows_accumulated_events():
    page = object.__new__(MonitorPage)
    page.activity_expanded = False
    page.activity_toggle_button = Mock()
    page.activity_panel = Mock()
    page.cards = Mock()
    page.refresh_activity_widget = Mock()
    page.toggle_activity()
    assert page.activity_expanded
    page.refresh_activity_widget.assert_called_once()


def test_schedule_refresh_does_not_create_duplicate_timer():
    page = object.__new__(MonitorPage)
    page.refresh_job = "already-scheduled"
    page.winfo_exists = Mock(return_value=True)
    page.after = Mock()
    page.schedule_refresh()
    page.after.assert_not_called()


def test_cancel_scheduled_refresh_cancels_existing_timer():
    page = object.__new__(MonitorPage)
    page.refresh_job = "timer-1"
    page.after_cancel = Mock()
    page.cancel_scheduled_refresh()
    page.after_cancel.assert_called_once_with("timer-1")
    assert page.refresh_job is None
