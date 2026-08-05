import threading
from unittest.mock import Mock, patch

from src.ui.main_window import MainWindow


def test_initial_page_failure_is_visible_and_does_not_escape():
    window = Mock()
    window.mostrar_dashboard.side_effect = RuntimeError("dashboard quebrado")

    with patch("src.ui.main_window.ctk.CTkLabel") as label:
        MainWindow.carregar_pagina_inicial(window)

    window.registrar_erro_inicializacao.assert_called_once()
    window.limpar.assert_called_once()
    label.return_value.pack.assert_called_once()
    window.status.configure.assert_called_once_with(
        text="Falha ao abrir Dashboard"
    )


def test_initial_page_success_loads_dashboard():
    window = Mock()

    MainWindow.carregar_pagina_inicial(window)

    window.mostrar_dashboard.assert_called_once_with()
    window.limpar.assert_not_called()


def test_close_starts_shutdown_outside_ui_thread():
    window = Mock()
    window._closing = False

    with patch.object(threading.Thread, "start") as start:
        MainWindow.fechar(window)

    assert window._closing is True
    start.assert_called_once()
    window.status.configure.assert_called_once_with(text="Encerrando...")
    window.after.assert_called_once_with(50, window._finish_close_when_ready)


def test_shutdown_exception_still_allows_window_to_close():
    window = Mock()
    window.monitor_runner.shutdown.side_effect = RuntimeError("falha no shutdown")

    MainWindow._shutdown_background(window)

    assert window._shutdown_result is False
    window.registrar_erro_inicializacao.assert_called_once()
