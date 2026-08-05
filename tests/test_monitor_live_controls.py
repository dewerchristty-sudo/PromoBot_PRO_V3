from pathlib import Path
from types import SimpleNamespace

from src.ui import monitor_page
from src.ui.monitor_page import MonitorPage


class Controller:
    def __init__(self):
        self.running = False
        self.calls = []
        self.stops = 0
    def start(self, **kwargs):
        self.calls.append(kwargs)
        self.running = True
        return True
    def stop(self):
        self.stops += 1
        self.running = False


class Runner:
    def __init__(self): self.starts = 0; self.stops = []
    def start(self): self.starts += 1
    def stop(self, wait=False): self.stops.append(wait)


class Guard:
    result = None
    def __init__(self, **kwargs): self.kwargs = kwargs
    def run(self, **kwargs): return self.result


def page(tmp_path):
    value = object.__new__(MonitorPage)
    value.database = SimpleNamespace(db=tmp_path / "promobot.db")
    value.runner = Runner()
    value._hunter_controller = Controller()
    value._hunter_mode = "stopped"
    value._hunter_started_at = None
    value._live_preflight_factory = Guard
    value.activities = []
    value.append_activity = value.activities.append
    value.carregar = lambda: None
    return value


def allowed():
    return SimpleNamespace(allowed=True, errors=(), details={
        "max_per_cycle": 1, "max_per_session": 2,
        "minimum_interval_seconds": 600,
        "destinations": ("120000000000@g.us",),
        "blocked_group": "",
    })


def test_analysis_button_starts_analysis_only(tmp_path):
    value = page(tmp_path)
    value.iniciar_analise()
    assert value._hunter_controller.calls == [{"mode": "analysis_only"}]
    assert value._hunter_mode == "analysis_only"
    assert value.runner.starts == 1


def test_live_blocked_never_starts_or_changes_transport(tmp_path, monkeypatch):
    value = page(tmp_path)
    Guard.result = SimpleNamespace(allowed=False, errors=("flags ausentes",), details={})
    shown = []
    monkeypatch.setattr(monitor_page.messagebox, "showerror", lambda *a, **k: shown.append(a))
    assert value.iniciar_live() is False
    assert shown and not value._hunter_controller.calls
    assert value.runner.starts == 0


def test_live_requires_dialog_and_exact_phrase(tmp_path, monkeypatch):
    value = page(tmp_path)
    Guard.result = allowed()
    monkeypatch.setattr(monitor_page.messagebox, "askokcancel", lambda *a, **k: True)
    monkeypatch.setattr(monitor_page.messagebox, "showwarning", lambda *a, **k: None)
    monkeypatch.setattr(monitor_page.simpledialog, "askstring", lambda *a, **k: "errado")
    assert value.iniciar_live() is False
    assert not value._hunter_controller.calls


def test_live_authorized_uses_first_run_limits_and_stop(tmp_path, monkeypatch):
    value = page(tmp_path)
    Guard.result = allowed()
    monkeypatch.setattr(monitor_page.messagebox, "askokcancel", lambda *a, **k: True)
    monkeypatch.setattr(monitor_page.simpledialog, "askstring", lambda *a, **k: "INICIAR LIVE")
    assert value.iniciar_live() is True
    assert value._hunter_controller.calls == [{
        "mode": "live", "limit": 1, "max_messages": 1,
        "per_store": 1, "stores": ("Amazon",),
        "max_session_messages": 2,
    }]
    assert value._hunter_mode == "live"
    value.parar()
    assert value._hunter_controller.stops == 1
    assert value._hunter_mode == "stopped"
    assert value.runner.stops == [False]


def test_frozen_interface_source_contains_separate_safe_controls():
    source = Path(monitor_page.__file__).read_text(encoding="utf-8")
    assert "Iniciar Análise" in source
    assert "Iniciar LIVE" in source
    assert "INICIAR LIVE" in source
    assert 'controller.start(mode="analysis_only")' not in source
