import sqlite3
from datetime import datetime, timedelta, timezone

from src.promotion_hunter.config import (
    ACCELERATED_MODE_KEY,
    operational_settings,
)
from src.promotion_hunter.delivery.policy import DeliveryPolicy


def config_database(path, value):
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE configuracoes_app (chave TEXT PRIMARY KEY, valor TEXT)"
    )
    connection.execute(
        "INSERT INTO configuracoes_app VALUES (?, ?)",
        (ACCELERATED_MODE_KEY, value),
    )
    connection.commit()
    connection.close()


def test_accelerated_mode_is_off_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("PROMOTION_HUNTER_ACCELERATED_MODE", raising=False)
    value = operational_settings(tmp_path / "missing.db")
    assert not value.accelerated
    assert (value.interval_minutes, value.max_messages_per_run) == (30, 1)
    assert value.min_seconds_between_messages == 600


def test_persisted_accelerated_values_are_loaded(tmp_path, monkeypatch):
    monkeypatch.delenv("PROMOTION_HUNTER_ACCELERATED_MODE", raising=False)
    path = tmp_path / "settings.db"
    config_database(path, "true")
    value = operational_settings(path)
    assert value.accelerated
    assert (value.interval_minutes, value.max_messages_per_run) == (2, 10)
    assert value.min_seconds_between_messages == 3


def test_disabling_restores_normal_values(tmp_path, monkeypatch):
    monkeypatch.delenv("PROMOTION_HUNTER_ACCELERATED_MODE", raising=False)
    path = tmp_path / "settings.db"
    config_database(path, "false")
    assert not operational_settings(path).accelerated


def test_three_second_interval_does_not_change_other_policy_rules():
    policy = DeliveryPolicy(minimum_interval_seconds=3)
    now = datetime(2026, 8, 1, 12, tzinfo=timezone.utc)
    values = dict(
        mode="live", live_enabled=True, destination="test", now=now,
        run_sent=0, hour_sent=0, session_sent=0,
    )
    blocked = policy.evaluate(
        **values, last_sent_at=(now - timedelta(seconds=2)).isoformat()
    )
    allowed = policy.evaluate(
        **values, last_sent_at=(now - timedelta(seconds=3)).isoformat()
    )
    assert blocked.reason == "intervalo_minimo"
    assert allowed.allowed


def test_accelerated_run_limit_is_effectively_ten_without_changing_normal():
    now = datetime(2026, 8, 1, 12, tzinfo=timezone.utc)
    accelerated = DeliveryPolicy(
        max_messages_per_run=10, minimum_interval_seconds=3
    )
    common = dict(
        mode="live", live_enabled=True, destination="test", now=now,
        last_sent_at=None,
    )
    assert accelerated.evaluate(
        **common, run_sent=9, hour_sent=9, session_sent=9
    ).allowed
    assert accelerated.evaluate(
        **common, run_sent=10, hour_sent=10, session_sent=10
    ).reason == "limite_execucao"

    normal = DeliveryPolicy(max_messages_per_run=3)
    assert normal.evaluate(
        **common, run_sent=0, hour_sent=5, session_sent=5
    ).reason == "limite_hora"
