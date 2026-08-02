"""Reset operacional seguro do PromoBot PRO V3.

O modo padrao de uso e ``--dry-run``. A aplicacao real exige confirmacao
explicita, ausencia de processos ativos, backup verificado e transacao SQLite.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
HUNTER_DB = "promotion_hunter.db"
MANIFEST = "manifest.json"
CONFIRMATION = "CONFIRMAR RESET OPERACIONAL"
QUEUE_RESET_STATUSES = ("pending", "failed", "sending")
EXPECTED_TABLES = {
    "promotion_hunter_delivery_queue",
    "promotion_hunter_delivery_attempts",
    "promotion_hunter_runs",
    "promotion_hunter_scheduler_state",
}
PRESERVED_DATABASES = (
    "promobot.db",
    "promotion_hunter_offer_pipeline.db",
    "offer_shadow.db",
    "monitor_telemetry.db",
)


class ResetSafetyError(RuntimeError):
    """Falha de seguranca que impede reset ou restauracao."""


@dataclass(frozen=True)
class PlannedOperation:
    database: str
    table: str
    status: str
    count: int
    operation: str
    reason: str
    backup_required: bool
    impact: str


@dataclass(frozen=True)
class ResetPlan:
    database: str
    operations: tuple[PlannedOperation, ...]
    preserved_databases: tuple[str, ...]
    expired_lock_files: tuple[str, ...] = ()

    @property
    def mutation_count(self) -> int:
        return sum(item.count for item in self.operations)


@dataclass(frozen=True)
class ProcessInfo:
    name: str
    pid: int
    parent_pid: int
    command_line: str | None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def connect_readonly(path: Path) -> sqlite3.Connection:
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=1)
    connection.row_factory = sqlite3.Row
    return connection


def table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }


def verify_database(connection: sqlite3.Connection) -> None:
    missing = EXPECTED_TABLES - table_names(connection)
    if missing:
        raise ResetSafetyError(
            "Schema inesperado; tabelas ausentes: " + ", ".join(sorted(missing))
        )
    result = connection.execute("PRAGMA integrity_check").fetchone()[0]
    if result != "ok":
        raise ResetSafetyError(f"Integridade SQLite falhou: {result}")


def count_by_status(connection: sqlite3.Connection, table: str) -> dict[str, int]:
    return {
        str(row[0]): int(row[1])
        for row in connection.execute(
            f'SELECT status, COUNT(*) FROM "{table}" GROUP BY status'
        )
    }


def build_plan(root: Path = ROOT, now: datetime | None = None) -> ResetPlan:
    now = now or utc_now()
    database = (root / HUNTER_DB).resolve()
    if not database.is_file():
        raise ResetSafetyError(f"Banco nao encontrado: {database}")
    connection = connect_readonly(database)
    try:
        verify_database(connection)
        queue = count_by_status(connection, "promotion_hunter_delivery_queue")
        runs = count_by_status(connection, "promotion_hunter_runs")
        cutoff = (now - timedelta(hours=2)).isoformat()
        abandoned = int(connection.execute(
            """
            SELECT COUNT(*) FROM promotion_hunter_runs
            WHERE status='running' AND started_at < ?
            """,
            (cutoff,),
        ).fetchone()[0])
        scheduler_stale = int(connection.execute(
            "SELECT COUNT(*) FROM promotion_hunter_scheduler_state WHERE running=1"
        ).fetchone()[0])
    finally:
        connection.close()

    operations = []
    for status in QUEUE_RESET_STATUSES:
        operations.append(PlannedOperation(
            str(database), "promotion_hunter_delivery_queue", status,
            queue.get(status, 0), "marcar como cancelled",
            "remover somente trabalho ativo/retry sem apagar auditoria", True,
            "item deixa de ser elegivel; linha e tentativas sao preservadas",
        ))
    operations.append(PlannedOperation(
        str(database), "promotion_hunter_runs", "running_abandonada",
        abandoned, "marcar como failed e preencher finished_at",
        "run ativa ha mais de 2 horas sem conclusao", True,
        "encerra apenas estado transitório; contagens e historico permanecem",
    ))
    operations.append(PlannedOperation(
        str(database), "promotion_hunter_scheduler_state", "running=1",
        scheduler_stale, "marcar running=0 e limpar next_run_at",
        "heartbeat e ponteiro de proxima execucao sao transitórios", True,
        "nao altera intervalo, janela, fontes ou configuracoes",
    ))
    disabled_file = root / "logs" / "disabled_stores.json"
    expired_locks = []
    if disabled_file.is_file():
        try:
            disabled = json.loads(disabled_file.read_text(encoding="utf-8") or "{}")
            local_now = now.astimezone().replace(tzinfo=None)
            for store, expiry in disabled.items():
                try:
                    parsed = datetime.fromisoformat(str(expiry))
                    if parsed.tzinfo is not None:
                        parsed = parsed.astimezone().replace(tzinfo=None)
                    if parsed <= local_now:
                        expired_locks.append(str(store))
                except (TypeError, ValueError):
                    pass
        except (OSError, ValueError, TypeError):
            pass
    operations.append(PlannedOperation(
        str(disabled_file.resolve()), "disabled_stores.json", "expirado",
        len(expired_locks), "remover somente entradas vencidas",
        "o Monitor considera expiração ISO passada como loja ativa", True,
        "bloqueios válidos e entradas malformadas permanecem intactos",
    ))
    preserved = tuple(
        str((root / name).resolve())
        for name in PRESERVED_DATABASES
        if (root / name).is_file()
    )
    return ResetPlan(
        str(database), tuple(operations), preserved, tuple(expired_locks)
    )


def _windows_processes() -> list[ProcessInfo]:
    """Le PID, pai e comando sem alterar o estado de nenhum processo."""
    script = (
        "Get-CimInstance Win32_Process | "
        "Select-Object Name,ProcessId,ParentProcessId,CommandLine | "
        "ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=15, check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError("consulta Win32_Process falhou")
    payload = json.loads(result.stdout)
    rows = payload if isinstance(payload, list) else [payload]
    return [
        ProcessInfo(
            str(row.get("Name") or ""), int(row["ProcessId"]),
            int(row.get("ParentProcessId") or 0), row.get("CommandLine"),
        )
        for row in rows
    ]


def _reset_process_command(command_line: str) -> bool:
    normalized = command_line.replace("/", "\\").casefold()
    script_match = re.search(
        r"(?:^|[\\\s\"'])scripts\\reset_operacional\.py(?:[\"']|\s|$)",
        normalized,
    )
    mode_match = re.search(r"(?:^|\s)--(?:dry-run|apply|restore)(?:\s|=|$)", normalized)
    return bool(script_match and mode_match)


def _related_process_ids(processes: list[ProcessInfo], current_pid: int) -> set[int]:
    """Retorna somente a cadeia comprovada por PID/ParentProcessId."""
    by_pid = {process.pid: process for process in processes}
    related = {current_pid}
    pid = current_pid
    seen: set[int] = set()
    while pid in by_pid and pid not in seen:
        seen.add(pid)
        parent = by_pid[pid].parent_pid
        if not parent:
            break
        related.add(parent)
        pid = parent
    changed = True
    while changed:
        changed = False
        for process in processes:
            if process.parent_pid in related and process.pid not in related:
                related.add(process.pid)
                changed = True
    return related


def _process_impediments(
    processes: list[ProcessInfo], current_pid: int,
) -> list[str]:
    related = _related_process_ids(processes, current_pid)
    found = []
    candidates = {"python.exe", "pythonw.exe", "promobot_pro_v3.exe"}
    for process in processes:
        name = process.name.casefold()
        if name not in candidates:
            continue
        if process.pid == current_pid:
            continue
        # Launchers/filhos Python so pertencem ao reset quando ambos os fatos
        # forem comprovados: parentesco por PID e comando exato deste script.
        if (
            process.pid in related
            and process.command_line is not None
            and _reset_process_command(process.command_line)
        ):
            continue
        if not process.command_line:
            found.append(f"{process.name} pid={process.pid} (CommandLine inconclusiva)")
        else:
            found.append(f"{process.name} pid={process.pid}")
    return found


def active_processes() -> list[str]:
    """Deteccao conservadora; nunca encerra processos.

    O named mutex cobre o Hunter oficial. Outros processos Python/PromoBot sao
    bloqueados por seguranca, exceto o proprio processo deste script.
    """
    found: list[str] = []
    if os.name == "nt":
        try:
            from src.promotion_hunter.process_lock import HunterProcessLock
            if HunterProcessLock.is_locked():
                found.append("named mutex do Promotion Hunter")
        except Exception as exc:
            found.append(f"nao foi possivel validar mutex: {type(exc).__name__}")
        try:
            found.extend(_process_impediments(_windows_processes(), os.getpid()))
        except Exception as exc:
            found.append(f"nao foi possivel enumerar processos: {type(exc).__name__}")
    return found


def assert_no_active_processes(detector: Callable[[], list[str]]) -> None:
    running = detector()
    if running:
        raise ResetSafetyError(
            "Processos ativos ou verificacao inconclusiva: " + "; ".join(running)
        )


def preflight_write_lock(database: Path) -> None:
    connection = sqlite3.connect(database, timeout=0.2)
    try:
        connection.execute("BEGIN IMMEDIATE")
        verify_database(connection)
        connection.rollback()
    except Exception:
        connection.rollback()
        raise ResetSafetyError(f"Banco bloqueado ou invalido: {database}")
    finally:
        connection.close()


def create_backup(
    root: Path, database: Path, tables: Iterable[str],
    now: datetime | None = None, extra_files: Iterable[Path] = (),
) -> Path:
    now = now or utc_now()
    stamp = now.astimezone().strftime("%Y-%m-%d_%H%M%S_%f")
    folder = root / "backups" / f"reset_operacional_{stamp}"
    folder.mkdir(parents=True, exist_ok=False)
    backup = folder / database.name
    try:
        source = connect_readonly(database)
        target = sqlite3.connect(backup)
        try:
            verify_database(source)
            source.backup(target)
        finally:
            target.close()
            source.close()
        checked = connect_readonly(backup)
        try:
            verify_database(checked)
        finally:
            checked.close()
        entry = {
            "original": str(database.resolve()),
            "backup": backup.name,
            "kind": "sqlite",
            "size": backup.stat().st_size,
            "sha256": sha256(backup),
            "created_at": now.isoformat(),
            "tables": sorted(set(tables)),
        }
        entries = [entry]
        for extra in extra_files:
            extra = extra.resolve()
            if not extra.is_file():
                raise ResetSafetyError(f"Arquivo candidato desapareceu: {extra}")
            extra_backup = folder / extra.name
            if extra_backup.exists():
                raise ResetSafetyError(f"Nome de backup duplicado: {extra.name}")
            shutil.copy2(extra, extra_backup)
            entries.append({
                "original": str(extra), "backup": extra_backup.name,
                "kind": "file", "size": extra_backup.stat().st_size,
                "sha256": sha256(extra_backup), "created_at": now.isoformat(),
                "tables": [],
            })
        manifest = {
            "version": 1,
            "kind": "promobot_operational_reset",
            "created_at": now.isoformat(),
            "root": str(root.resolve()),
            "files": entries,
        }
        (folder / MANIFEST).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        for backed_up in entries:
            if sha256(folder / backed_up["backup"]) != backed_up["sha256"]:
                raise ResetSafetyError("Hash do backup divergiu apos criacao")
        return folder
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise


def apply_reset(
    root: Path = ROOT, confirmation: str = "",
    detector: Callable[[], list[str]] = active_processes,
    now: datetime | None = None,
    failure_hook: Callable[[sqlite3.Connection], None] | None = None,
) -> tuple[ResetPlan, Path]:
    if confirmation != CONFIRMATION:
        raise ResetSafetyError("Confirmacao literal ausente ou incorreta")
    assert_no_active_processes(detector)
    now = now or utc_now()
    plan = build_plan(root, now)
    database = Path(plan.database)
    preflight_write_lock(database)
    expected = {(op.table, op.status): op.count for op in plan.operations}
    changed_tables = {op.table for op in plan.operations if op.count}
    disabled_file = root / "logs" / "disabled_stores.json"
    extra_files = (disabled_file,) if plan.expired_lock_files else ()
    backup_folder = create_backup(
        root, database, changed_tables, now, extra_files=extra_files
    )

    connection = sqlite3.connect(database, timeout=0.2)
    disabled_replaced = False
    try:
        connection.execute("BEGIN IMMEDIATE")
        verify_database(connection)
        current = build_plan(root, now)
        actual = {(op.table, op.status): op.count for op in current.operations}
        if actual != expected:
            raise ResetSafetyError("Estado mudou depois do planejamento; reset abortado")
        reason = "reset operacional seguro; registro preservado para auditoria"
        placeholders = ",".join("?" for _ in QUEUE_RESET_STATUSES)
        connection.execute(
            f"""
            UPDATE promotion_hunter_delivery_queue
            SET status='cancelled', last_error=?, updated_at=?
            WHERE status IN ({placeholders})
            """,
            (reason, now.isoformat(), *QUEUE_RESET_STATUSES),
        )
        cutoff = (now - timedelta(hours=2)).isoformat()
        connection.execute(
            """
            UPDATE promotion_hunter_runs SET status='failed', finished_at=?
            WHERE status='running' AND started_at < ?
            """,
            (now.isoformat(), cutoff),
        )
        connection.execute(
            """
            UPDATE promotion_hunter_scheduler_state
            SET running=0, next_run_at=NULL,
                last_error='reset operacional seguro: estado transitório encerrado',
                updated_at=? WHERE running=1
            """,
            (now.isoformat(),),
        )
        if failure_hook:
            failure_hook(connection)
        if plan.expired_lock_files:
            current_disabled = json.loads(
                disabled_file.read_text(encoding="utf-8") or "{}"
            )
            current_expired = set(build_plan(root, now).expired_lock_files)
            if current_expired != set(plan.expired_lock_files):
                raise ResetSafetyError("Bloqueios temporarios mudaram; reset abortado")
            for store in plan.expired_lock_files:
                current_disabled.pop(store, None)
            temporary = disabled_file.with_suffix(".json.reset.tmp")
            temporary.write_text(
                json.dumps(current_disabled, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(temporary, disabled_file)
            disabled_replaced = True
        connection.commit()
    except Exception:
        connection.rollback()
        if disabled_replaced:
            manifest = load_manifest(backup_folder)
            entry = next(
                item for item in manifest["files"]
                if Path(item["original"]).resolve() == disabled_file.resolve()
            )
            shutil.copy2(backup_folder / entry["backup"], disabled_file)
        raise
    finally:
        connection.close()
    return plan, backup_folder


def load_manifest(folder: Path) -> dict:
    manifest_path = folder / MANIFEST
    if not manifest_path.is_file():
        raise ResetSafetyError(f"Manifesto ausente: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("kind") != "promobot_operational_reset":
        raise ResetSafetyError("Manifesto nao pertence ao reset operacional")
    if not manifest.get("files"):
        raise ResetSafetyError("Manifesto nao contem arquivos")
    return manifest


def restore_backup(
    folder: Path, root: Path = ROOT,
    detector: Callable[[], list[str]] = active_processes,
    now: datetime | None = None,
) -> Path:
    assert_no_active_processes(detector)
    folder = folder.resolve()
    manifest = load_manifest(folder)
    allowed = {
        (root / HUNTER_DB).resolve(),
        (root / "logs" / "disabled_stores.json").resolve(),
    }
    resolved = []
    for entry in manifest["files"]:
        source = (folder / entry["backup"]).resolve()
        target = Path(entry["original"]).resolve()
        if target not in allowed or source.parent != folder:
            raise ResetSafetyError("Manifesto tentou restaurar arquivo fora do escopo")
        if not source.is_file() or sha256(source) != entry["sha256"]:
            raise ResetSafetyError("Backup ausente ou hash invalido")
        resolved.append((entry, source, target))
    database_target = (root / HUNTER_DB).resolve()
    preflight_write_lock(database_target)
    current_extras = tuple(
        target for _entry, _source, target in resolved
        if target != database_target and target.is_file()
    )
    safety_backup = create_backup(
        root, database_target, EXPECTED_TABLES, now or utc_now(),
        extra_files=current_extras,
    )
    temporaries = []
    try:
        for entry, source, target in resolved:
            temporary = target.with_name(target.name + ".restore.tmp")
            if temporary.exists():
                raise ResetSafetyError(f"Arquivo temporario ja existe: {temporary}")
            shutil.copy2(source, temporary)
            temporaries.append(temporary)
            if sha256(temporary) != entry["sha256"]:
                raise ResetSafetyError("Copia temporaria falhou no hash")
            if entry.get("kind") == "sqlite":
                checked = connect_readonly(temporary)
                try:
                    verify_database(checked)
                finally:
                    checked.close()
        for (_entry, _source, target), temporary in zip(resolved, temporaries):
            os.replace(temporary, target)
    finally:
        for temporary in temporaries:
            if temporary.exists():
                temporary.unlink()
    return safety_backup


def print_plan(plan: ResetPlan, processes: list[str]) -> None:
    print("=" * 72)
    print("PROMOBOT PRO V3 - RESET OPERACIONAL")
    print("MODO: DRY-RUN")
    print("=" * 72)
    print("Nenhuma alteracao sera realizada.\n")
    print(f"Banco candidato: {plan.database}")
    for operation in plan.operations:
        print(
            f"- {operation.table} | {operation.status}: {operation.count} | "
            f"{operation.operation} | motivo: {operation.reason} | "
            f"backup: {'sim' if operation.backup_required else 'nao'} | "
            f"impacto: {operation.impact}"
        )
    print("\nBancos preservados integralmente:")
    for database in plan.preserved_databases:
        print(f"- {database}")
    print("\nTentativas concluídas, sent, cancelled, decisoes e logs: preservar")
    print(
        "disabled_stores.json: remover somente bloqueios comprovadamente vencidos; "
        "preservar válidos/malformados"
    )
    print("Processos/impedimentos:", "; ".join(processes) if processes else "nenhum")
    print(
        "RESULTADO:",
        "NAO ELEGIVEL enquanto houver impedimentos"
        if processes else "ELEGIVEL para reset futuro mediante confirmacao",
    )
    print("Nenhum dado foi modificado.")
    print("=" * 72)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    mode = value.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--restore", type=Path)
    value.add_argument("--confirm", default="")
    value.add_argument("--root", type=Path, default=ROOT)
    return value


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    root = args.root.resolve()
    try:
        if args.dry_run:
            print_plan(build_plan(root), active_processes())
        elif args.apply:
            plan, folder = apply_reset(root, args.confirm)
            print(f"Reset aplicado: {plan.mutation_count} candidatos")
            print(f"Backup: {folder}")
        else:
            safety = restore_backup(args.restore, root)
            print(f"Restauracao concluida. Backup do estado anterior: {safety}")
        return 0
    except (ResetSafetyError, sqlite3.Error, OSError, ValueError) as exc:
        print(f"ABORTADO: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
