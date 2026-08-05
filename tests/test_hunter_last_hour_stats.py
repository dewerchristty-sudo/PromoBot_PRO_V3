import sqlite3
from datetime import datetime, timedelta, timezone

from src.ui.monitor_page import HunterStatusReader, MonitorPage


REFERENCE = datetime(2026, 8, 1, 18, 0, tzinfo=timezone.utc)
TIMESTAMPS = (
    "2026-08-01T16:59:00+00:00",  # 61 minutos, UTC e separador T
    "2026-08-01T14:00:00-03:00",  # exatamente 60 minutos, com offset
    "2026-08-01 17:01:00",        # 59 minutos, formato antigo com espaço
)


def _connect(path):
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def _python_in_last_hour(value):
    instant = datetime.fromisoformat(value)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    return instant.astimezone(timezone.utc) >= REFERENCE - timedelta(hours=1)


def test_last_hour_stats_match_python_for_iso_offsets_and_legacy_format(
    tmp_path, monkeypatch
):
    pipeline_path = tmp_path / "pipeline.db"
    hunter_path = tmp_path / "hunter.db"

    pipeline = _connect(pipeline_path)
    pipeline.execute(
        "CREATE TABLE offer_pipeline_runs ("
        "created_at TEXT, received_count INTEGER, valid_count INTEGER, "
        "approved_count INTEGER, blocked_count INTEGER, duplicate_count INTEGER, "
        "discarded_count INTEGER)"
    )
    for created_at, amount in zip(TIMESTAMPS, (100, 10, 1)):
        pipeline.execute(
            "INSERT INTO offer_pipeline_runs VALUES (?, ?, ?, ?, 0, 0, 0)",
            (created_at, amount, amount, amount),
        )
    pipeline.commit()
    pipeline.close()

    hunter = _connect(hunter_path)
    hunter.execute(
        "CREATE TABLE promotion_hunter_delivery_queue (status TEXT, sent_at TEXT)"
    )
    hunter.execute(
        "CREATE TABLE promotion_hunter_delivery_attempts (started_at TEXT)"
    )
    for timestamp in TIMESTAMPS:
        hunter.execute(
            "INSERT INTO promotion_hunter_delivery_queue VALUES ('sent', ?)",
            (timestamp,),
        )
        hunter.execute(
            "INSERT INTO promotion_hunter_delivery_attempts VALUES (?)",
            (timestamp,),
        )
    hunter.commit()
    hunter.close()

    monkeypatch.setattr(
        HunterStatusReader, "_pipeline_db", staticmethod(lambda: _connect(pipeline_path))
    )
    monkeypatch.setattr(
        HunterStatusReader, "_hunter_db", staticmethod(lambda: _connect(hunter_path))
    )

    expected_rows = sum(_python_in_last_hour(value) for value in TIMESTAMPS)
    pipeline_stats = HunterStatusReader._pipeline_stats(REFERENCE.isoformat())
    delivery_stats = HunterStatusReader._delivery_stats(REFERENCE.isoformat())

    assert expected_rows == 2
    assert pipeline_stats["received"] == 11
    assert pipeline_stats["approved"] == 11
    assert delivery_stats == {"sent_hour": 2, "attempts_hour": 2}


class _LabelSpy:
    def __init__(self):
        self.text = None

    def configure(self, *, text):
        self.text = text


def test_interface_cards_display_reader_last_hour_values(monkeypatch):
    labels = {
        key: _LabelSpy()
        for key in (
            "hunter_scheduler",
            "hunter_status",
            "hunter_stores",
            "hunter_last",
            "hunter_pipeline",
            "hunter_delivery",
            "hunter_security",
            "hunter_blocked",
        )
    }
    snapshot = {
        "scheduler": "stopped",
        "current_run": None,
        "last_run": None,
        "pipeline": {
            "received": 11,
            "valid": 11,
            "approved": 11,
            "blocked": 0,
            "duplicates": 0,
            "discarded": 0,
        },
        "deliveries": {"sent_hour": 2, "attempts_hour": 2},
        "live_delivery": False,
        "blocked_group": "grupo",
    }
    monkeypatch.setattr(HunterStatusReader, "read", classmethod(lambda cls: snapshot))
    page = object.__new__(MonitorPage)
    page.hunter_values = labels

    page.render_hunter_status()

    assert "Receb.: 11" in labels["hunter_pipeline"].text
    assert "Aprov.: 11" in labels["hunter_pipeline"].text
    assert "Enviadas: 2" in labels["hunter_delivery"].text
    assert "Tentat.: 2" in labels["hunter_delivery"].text
