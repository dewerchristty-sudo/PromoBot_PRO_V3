import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts import reset_operacional as reset


NOW = datetime(2026, 8, 2, 8, tzinfo=timezone.utc)


def create_database(root: Path) -> Path:
    database = root / reset.HUNTER_DB
    connection = sqlite3.connect(database)
    connection.executescript("""
        CREATE TABLE promotion_hunter_delivery_queue(
            id INTEGER PRIMARY KEY, status TEXT, last_error TEXT,
            updated_at TEXT
        );
        CREATE TABLE promotion_hunter_delivery_attempts(
            id INTEGER PRIMARY KEY, queue_id INTEGER, status TEXT,
            error_message TEXT
        );
        CREATE TABLE promotion_hunter_runs(
            run_id TEXT PRIMARY KEY, status TEXT, collected_count INTEGER,
            unique_count INTEGER, started_at TEXT, finished_at TEXT
        );
        CREATE TABLE promotion_hunter_scheduler_state(
            singleton_id INTEGER PRIMARY KEY, running INTEGER,
            last_run_at TEXT, next_run_at TEXT, last_error TEXT,
            updated_at TEXT
        );
        CREATE TABLE promotion_hunter_decisions(id INTEGER PRIMARY KEY, reason TEXT);
        CREATE TABLE promotion_hunter_sources(source_id TEXT PRIMARY KEY, configuration_json TEXT);
    """)
    statuses = ["pending", "failed", "sending", "sent", "cancelled"]
    for number, status in enumerate(statuses, 1):
        connection.execute(
            "INSERT INTO promotion_hunter_delivery_queue VALUES(?,?,?,?)",
            (number, status, f"erro-{status}", "antes"),
        )
        connection.execute(
            "INSERT INTO promotion_hunter_delivery_attempts VALUES(?,?,?,?)",
            (number, number, "sent" if status == "sent" else "failed", "auditoria"),
        )
    old = (NOW - timedelta(hours=3)).isoformat()
    recent = (NOW - timedelta(minutes=30)).isoformat()
    connection.executemany(
        "INSERT INTO promotion_hunter_runs VALUES(?,?,?,?,?,?)",
        [
            ("success", "success", 10, 10, old, old),
            ("failed", "failed", 0, 0, old, old),
            ("abandoned", "running", 2, 2, old, None),
            ("recent", "running", 1, 1, recent, None),
        ],
    )
    connection.execute(
        "INSERT INTO promotion_hunter_scheduler_state VALUES(1,1,?,?,?,?)",
        (old, recent, "erro transitório", "antes"),
    )
    connection.execute("INSERT INTO promotion_hunter_decisions VALUES(1,'preservar')")
    connection.execute("INSERT INTO promotion_hunter_sources VALUES('fonte','config')")
    connection.commit()
    connection.close()
    return database


def bytes_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(database: Path, query: str):
    connection = sqlite3.connect(database)
    try:
        return connection.execute(query).fetchall()
    finally:
        connection.close()


@pytest.fixture
def workspace(tmp_path):
    create_database(tmp_path)
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "disabled_stores.json").write_text(
        json.dumps({
            "Expirada": "2026-08-02T04:00:00",
            "Valida": "2026-08-02T06:00:00",
            "Malformada": "nao-apagar",
        }),
        encoding="utf-8",
    )
    return tmp_path


def apply(workspace, **kwargs):
    return reset.apply_reset(
        workspace, reset.CONFIRMATION, detector=lambda: [], now=NOW, **kwargs
    )


def test_dry_run_does_not_change_database_bytes(workspace):
    database = workspace / reset.HUNTER_DB
    before = database.read_bytes()
    plan = reset.build_plan(workspace, NOW)
    reset.print_plan(plan, [])
    assert database.read_bytes() == before
    assert not (workspace / "backups").exists()


def test_plan_is_explicit_and_preserves_other_databases(workspace):
    (workspace / "promobot.db").write_bytes(b"preservar")
    plan = reset.build_plan(workspace, NOW)
    counts = {(item.table, item.status): item.count for item in plan.operations}
    assert counts[("promotion_hunter_delivery_queue", "pending")] == 1
    assert counts[("promotion_hunter_delivery_queue", "failed")] == 1
    assert counts[("promotion_hunter_delivery_queue", "sending")] == 1
    assert counts[("promotion_hunter_runs", "running_abandonada")] == 1
    assert counts[("disabled_stores.json", "expirado")] == 1
    assert plan.expired_lock_files == ("Expirada",)
    assert str((workspace / "promobot.db").resolve()) in plan.preserved_databases


def test_apply_preserves_audit_history_config_schema_and_final_statuses(workspace):
    database = workspace / reset.HUNTER_DB
    schema_before = rows(database, "SELECT sql FROM sqlite_master ORDER BY name")
    attempts_before = rows(database, "SELECT * FROM promotion_hunter_delivery_attempts")
    decisions_before = rows(database, "SELECT * FROM promotion_hunter_decisions")
    sources_before = rows(database, "SELECT * FROM promotion_hunter_sources")

    apply(workspace)

    statuses = dict(rows(database, "SELECT id,status FROM promotion_hunter_delivery_queue"))
    assert statuses == {1: "cancelled", 2: "cancelled", 3: "cancelled", 4: "sent", 5: "cancelled"}
    assert rows(database, "SELECT * FROM promotion_hunter_delivery_attempts") == attempts_before
    assert rows(database, "SELECT * FROM promotion_hunter_decisions") == decisions_before
    assert rows(database, "SELECT * FROM promotion_hunter_sources") == sources_before
    assert rows(database, "SELECT sql FROM sqlite_master ORDER BY name") == schema_before


def test_only_abandoned_run_is_closed_and_scheduler_transient_state_resets(workspace):
    database = workspace / reset.HUNTER_DB
    apply(workspace)
    runs = dict(rows(database, "SELECT run_id,status FROM promotion_hunter_runs"))
    assert runs == {
        "success": "success", "failed": "failed",
        "abandoned": "failed", "recent": "running",
    }
    scheduler = rows(
        database,
        "SELECT running,next_run_at,last_error FROM promotion_hunter_scheduler_state",
    )[0]
    assert scheduler[0] == 0 and scheduler[1] is None
    assert "reset operacional seguro" in scheduler[2]


def test_only_expired_temporary_block_is_removed(workspace):
    disabled_file = workspace / "logs" / "disabled_stores.json"
    apply(workspace)
    disabled = json.loads(disabled_file.read_text(encoding="utf-8"))
    assert disabled == {"Valida": "2026-08-02T06:00:00", "Malformada": "nao-apagar"}


def test_backup_precedes_change_and_manifest_hash_matches(workspace):
    database = workspace / reset.HUNTER_DB
    original_rows = rows(database, "SELECT * FROM promotion_hunter_delivery_queue")
    _plan, folder = apply(workspace)
    manifest = json.loads((folder / reset.MANIFEST).read_text(encoding="utf-8"))
    entry = manifest["files"][0]
    backup = folder / entry["backup"]
    assert entry["sha256"] == bytes_hash(backup)
    assert entry["size"] == backup.stat().st_size
    assert rows(backup, "SELECT * FROM promotion_hunter_delivery_queue") == original_rows


def test_backup_failure_aborts_before_database_change(workspace, monkeypatch):
    database = workspace / reset.HUNTER_DB
    before = database.read_bytes()
    monkeypatch.setattr(reset, "create_backup", lambda *a, **k: (_ for _ in ()).throw(OSError("falha")))
    with pytest.raises(OSError):
        apply(workspace)
    assert database.read_bytes() == before


def test_failure_in_transaction_rolls_back_every_change(workspace):
    database = workspace / reset.HUNTER_DB
    logical_before = rows(database, "SELECT * FROM promotion_hunter_delivery_queue")
    with pytest.raises(RuntimeError):
        apply(workspace, failure_hook=lambda _connection: (_ for _ in ()).throw(RuntimeError("boom")))
    assert rows(database, "SELECT * FROM promotion_hunter_delivery_queue") == logical_before
    assert rows(database, "SELECT status FROM promotion_hunter_runs WHERE run_id='abandoned'") == [("running",)]


def test_active_process_aborts_without_backup_or_change(workspace):
    database = workspace / reset.HUNTER_DB
    before = database.read_bytes()
    with pytest.raises(reset.ResetSafetyError, match="Processos ativos"):
        reset.apply_reset(
            workspace, reset.CONFIRMATION,
            detector=lambda: ["PromoBot pid=123"], now=NOW,
        )
    assert database.read_bytes() == before
    assert not (workspace / "backups").exists()


def process(name, pid, parent, command):
    return reset.ProcessInfo(name, pid, parent, command)


def test_process_detector_ignores_current_reset_and_its_strict_chain():
    processes = [
        process("powershell.exe", 10, 0, "powershell.exe"),
        process("cmd.exe", 20, 10, r"cmd /c RESET_PROMOBOT_OPERACIONAL.bat"),
        process("python.exe", 30, 20, r".venv\Scripts\python.exe scripts\reset_operacional.py --dry-run"),
        process("python.exe", 40, 30, r".venv\Scripts\python.exe scripts\reset_operacional.py --dry-run"),
    ]
    # No Windows, o launcher do venv (PID 30) pode criar o interpretador
    # efetivo (PID atual 40) mantendo a mesma linha de comando.
    assert reset._process_impediments(processes, 40) == []


@pytest.mark.parametrize("script", ["main.py", "_start_multi_store.py"])
def test_operational_python_process_blocks_reset(script):
    processes = [
        process("python.exe", 30, 20, r"python scripts\reset_operacional.py --dry-run"),
        process("python.exe", 99, 50, f"python {script}"),
    ]
    assert reset._process_impediments(processes, 30) == ["python.exe pid=99"]


@pytest.mark.parametrize("command", [None, "", "python unknown.py"])
def test_unknown_or_inconclusive_python_blocks_reset(command):
    processes = [
        process("python.exe", 30, 20, r"python scripts\reset_operacional.py --restore backup"),
        process("python.exe", 99, 50, command),
    ]
    impediments = reset._process_impediments(processes, 30)
    assert len(impediments) == 1
    assert "pid=99" in impediments[0]


def test_unrelated_reset_command_is_not_excluded():
    processes = [
        process("python.exe", 30, 20, r"python scripts\reset_operacional.py --dry-run"),
        process("python.exe", 99, 50, r"python scripts\reset_operacional.py --apply"),
    ]
    assert reset._process_impediments(processes, 30) == ["python.exe pid=99"]


def test_named_mutex_still_blocks(monkeypatch):
    import src.promotion_hunter.process_lock as process_lock

    monkeypatch.setattr(process_lock.HunterProcessLock, "is_locked", lambda: True)
    monkeypatch.setattr(reset, "_windows_processes", lambda: [])
    monkeypatch.setattr(reset.os, "name", "nt")
    assert "named mutex do Promotion Hunter" in reset.active_processes()


def test_wrong_confirmation_aborts(workspace):
    with pytest.raises(reset.ResetSafetyError, match="Confirmacao"):
        reset.apply_reset(workspace, "sim", detector=lambda: [], now=NOW)


def test_locked_database_aborts(workspace):
    database = workspace / reset.HUNTER_DB
    locker = sqlite3.connect(database)
    locker.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(reset.ResetSafetyError, match="bloqueado"):
            apply(workspace)
    finally:
        locker.rollback()
        locker.close()


def test_restore_recovers_original_and_creates_safety_backup(workspace):
    database = workspace / reset.HUNTER_DB
    original = rows(database, "SELECT * FROM promotion_hunter_delivery_queue")
    disabled_file = workspace / "logs" / "disabled_stores.json"
    disabled_original = disabled_file.read_bytes()
    _plan, folder = apply(workspace)
    assert rows(database, "SELECT * FROM promotion_hunter_delivery_queue") != original
    safety = reset.restore_backup(folder, workspace, detector=lambda: [], now=NOW + timedelta(seconds=1))
    assert rows(database, "SELECT * FROM promotion_hunter_delivery_queue") == original
    assert disabled_file.read_bytes() == disabled_original
    assert (safety / reset.MANIFEST).is_file()


def test_restore_rejects_tampered_backup(workspace):
    _plan, folder = apply(workspace)
    manifest = json.loads((folder / reset.MANIFEST).read_text(encoding="utf-8"))
    backup = folder / manifest["files"][0]["backup"]
    backup.write_bytes(backup.read_bytes() + b"tamper")
    with pytest.raises(reset.ResetSafetyError, match="hash"):
        reset.restore_backup(folder, workspace, detector=lambda: [], now=NOW)


def test_restore_uses_same_process_blocking_rules(workspace):
    database = workspace / reset.HUNTER_DB
    before = database.read_bytes()
    with pytest.raises(reset.ResetSafetyError, match="Processos ativos"):
        reset.restore_backup(
            workspace / "backup-nao-deve-ser-lido", workspace,
            detector=lambda: ["python.exe pid=99"], now=NOW,
        )
    assert database.read_bytes() == before
    assert not (workspace / "backups").exists()


def test_no_transport_or_process_mutation_apis_are_used():
    source = Path(reset.__file__).read_text(encoding="utf-8").casefold()
    forbidden = (
        "requests.", "httpx.", "whatsapp", "evolution",
        "terminateprocess", "stop-process", "taskkill", "kill(",
    )
    assert not [token for token in forbidden if token in source]
