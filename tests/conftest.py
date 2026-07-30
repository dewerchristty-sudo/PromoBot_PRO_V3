import hashlib
import sqlite3
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REAL_MONITOR_TELEMETRY = PROJECT_ROOT / "monitor_telemetry.db"


def _database_snapshot(path):
    if not path.exists():
        return None
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        counts = tuple(
            connection.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
            for table in ("monitor_execution_runs", "monitor_store_runs")
        )
    stat = path.stat()
    return digest, stat.st_size, stat.st_mtime_ns, counts


@pytest.fixture(scope="session", autouse=True)
def protect_real_monitor_telemetry_database():
    before = _database_snapshot(REAL_MONITOR_TELEMETRY)
    yield
    assert _database_snapshot(REAL_MONITOR_TELEMETRY) == before, (
        "A suíte de testes alterou monitor_telemetry.db real"
    )


@pytest.fixture(autouse=True)
def isolate_default_monitor_telemetry(monkeypatch, tmp_path):
    monkeypatch.setenv("ENABLE_MONITOR_TELEMETRY", "false")
    monkeypatch.setenv(
        "MONITOR_TELEMETRY_DB_PATH",
        str(tmp_path / "monitor_telemetry_test.db"),
    )
