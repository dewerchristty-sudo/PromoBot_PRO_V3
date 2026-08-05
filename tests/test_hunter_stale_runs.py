import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from src.ui.monitor_page import HunterStatusReader


NOW = datetime(2026, 8, 1, 18, 0, tzinfo=timezone.utc)


def _connect(path):
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def _database(tmp_path, *, running=False, heartbeat=None, error="", runs=()):
    path = tmp_path / "hunter-status.db"
    connection = _connect(path)
    connection.execute(
        "CREATE TABLE promotion_hunter_scheduler_state ("
        "singleton_id INTEGER, running INTEGER, last_error TEXT, updated_at TEXT)"
    )
    connection.execute(
        "INSERT INTO promotion_hunter_scheduler_state VALUES (1, ?, ?, ?)",
        (int(running), error, heartbeat),
    )
    connection.execute(
        "CREATE TABLE promotion_hunter_runs ("
        "status TEXT, collected_count INTEGER, unique_count INTEGER, "
        "started_at TEXT, finished_at TEXT)"
    )
    connection.executemany(
        "INSERT INTO promotion_hunter_runs VALUES (?, 0, 0, ?, ?)", runs
    )
    connection.commit()
    connection.close()
    return path


def _install(monkeypatch, path, process_active=False):
    monkeypatch.setattr(
        HunterStatusReader, "_hunter_db", staticmethod(lambda: _connect(path))
    )
    monkeypatch.setattr(
        HunterStatusReader,
        "_is_process_active",
        classmethod(lambda cls: process_active),
    )


def test_recent_running_run_with_fresh_heartbeat_is_executing(tmp_path, monkeypatch):
    path = _database(
        tmp_path,
        running=True,
        heartbeat=(NOW - timedelta(seconds=5)).isoformat(),
        runs=(("running", (NOW - timedelta(seconds=10)).isoformat(), None),),
    )
    _install(monkeypatch, path, process_active=True)
    assert HunterStatusReader._scheduler_state(NOW) == "active"
    assert HunterStatusReader._current_run(NOW) is not None


@pytest.mark.parametrize("stale_count", (1, 2))
def test_old_running_runs_are_not_current(tmp_path, monkeypatch, stale_count):
    runs = tuple(
        ("running", (NOW - timedelta(hours=index + 1)).isoformat(), None)
        for index in range(stale_count)
    )
    path = _database(
        tmp_path,
        running=True,
        heartbeat=(NOW - timedelta(seconds=5)).isoformat(),
        runs=runs,
    )
    _install(monkeypatch, path, process_active=True)
    assert HunterStatusReader._scheduler_state(NOW) == "active"
    assert HunterStatusReader._current_run(NOW) is None


def test_active_scheduler_without_current_run_is_waiting_state(tmp_path, monkeypatch):
    path = _database(
        tmp_path,
        running=True,
        heartbeat=(NOW - timedelta(minutes=30)).isoformat(),
        runs=(("success", (NOW - timedelta(minutes=35)).isoformat(), NOW.isoformat()),),
    )
    _install(monkeypatch, path, process_active=True)
    assert HunterStatusReader._scheduler_state(NOW) == "active"
    assert HunterStatusReader._current_run(NOW) is None


def test_stopped_scheduler_is_stopped(tmp_path, monkeypatch):
    path = _database(tmp_path, running=False, heartbeat=NOW.isoformat())
    _install(monkeypatch, path)
    assert HunterStatusReader._scheduler_state(NOW) == "stopped"
    assert HunterStatusReader._current_run(NOW) is None


def test_expired_heartbeat_does_not_keep_scheduler_or_run_active(
    tmp_path, monkeypatch
):
    path = _database(
        tmp_path,
        running=True,
        heartbeat=(NOW - timedelta(hours=2)).isoformat(),
        runs=(("running", (NOW - timedelta(seconds=10)).isoformat(), None),),
    )
    _install(monkeypatch, path, process_active=True)
    assert HunterStatusReader._scheduler_state(NOW) == "degraded"
    assert HunterStatusReader._current_run(NOW) is None


def test_fresh_scheduler_error_is_degraded(tmp_path, monkeypatch):
    path = _database(
        tmp_path,
        running=True,
        heartbeat=NOW.isoformat(),
        error="falha controlada",
    )
    _install(monkeypatch, path, process_active=True)
    assert HunterStatusReader._scheduler_state(NOW) == "degraded"
