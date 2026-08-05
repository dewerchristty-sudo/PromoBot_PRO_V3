import json
import threading

import main


class _FakeWindow:
    current_page = "dashboard"
    shutdown_clean = True


class _FakePromoBot:
    def __init__(self, db_path=None, startup_probe=False):
        self.db_path = db_path
        self.startup_probe = startup_probe
        self.app = _FakeWindow()

    def run(self):
        return None


def test_startup_probe_isolated_without_hunter_or_network(tmp_path, monkeypatch):
    import src.app

    monkeypatch.setattr(src.app, "PromoBot", _FakePromoBot)
    monkeypatch.setattr(main, "__version__", "test")
    output = tmp_path / "result.json"

    handled = main._startup_probe_cli([
        "--startup-probe",
        "--database", str(tmp_path / "probe.db"),
        "--output", str(output),
    ])

    assert handled is True
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["dashboard_loaded"] is True
    assert result["shutdown_clean"] is True
    assert result["scheduler_started"] is False
    assert result["hunter_started"] is False
    assert result["evolution_post_count"] == 0
    assert result["residual_threads"] == []


def test_startup_probe_reports_frozen_runtime(tmp_path, monkeypatch):
    import src.app

    monkeypatch.setattr(src.app, "PromoBot", _FakePromoBot)
    monkeypatch.setattr(main.sys, "frozen", True, raising=False)
    output = tmp_path / "result.json"
    main._startup_probe_cli([
        "--startup-probe", "--database", str(tmp_path / "db"),
        "--output", str(output),
    ])
    assert json.loads(output.read_text(encoding="utf-8"))["frozen"] is True
    assert threading.enumerate() == [threading.current_thread()]
