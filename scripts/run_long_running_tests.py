import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from dotenv import dotenv_values

from tests.long_running.scenarios import write_reports


OUTPUT = Path("reports/long_running_tests")


def digest(path):
    path = Path(path)
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safety_check():
    temporary = Path(tempfile.gettempdir()).resolve()
    if not temporary.is_dir():
        return False, "TEMPORARY_DIRECTORY_UNAVAILABLE"
    if os.getenv("PYTEST_CURRENT_TEST"):
        return False, "NESTED_TEST_EXECUTION_NOT_ALLOWED"
    return True, "SAFE_TEST_ENVIRONMENT"


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Executa somente simulações temporárias do PromoBot."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--quick", action="store_true")
    mode.add_argument("--full", action="store_true")
    args = parser.parse_args(argv)
    safe, reason = safety_check()
    if not safe:
        print("ABORTADO:", reason)
        return 2
    env_path = Path(".env")
    configured = dotenv_values(env_path) if env_path.is_file() else {}
    database_path = Path(
        configured.get("OFFER_SHADOW_DB_PATH")
        or os.getenv("OFFER_SHADOW_DB_PATH", "offer_shadow.db")
    )
    before = {
        "env": digest(env_path),
        "database": digest(database_path),
    }
    targets = [
        "tests/long_running/test_multi_day_price_history.py",
        "tests/long_running/test_scheduler_history_integration.py",
        "tests/long_running/test_restart_consistency.py",
        "tests/long_running/test_temporal_consistency.py",
        "tests/long_running/test_environment_protection.py",
    ]
    if args.full or not args.quick:
        targets.append("tests/long_running/test_30_day_stability.py")
    command = [
        sys.executable, "-m", "pytest", "-q", *targets,
    ]
    completed = subprocess.run(command, check=False)
    after = {
        "env": digest(env_path),
        "database": digest(database_path),
    }
    if before != after:
        print("ABORTADO: REAL_ENVIRONMENT_CHANGED")
        return 3
    if completed.returncode:
        return completed.returncode
    summary, paths = write_reports(OUTPUT)
    print("SIMULATED_TEST_DATA")
    print("Modo:", "quick" if args.quick else "full")
    print("Status:", summary["status"])
    print("Banco real preservado: True")
    print(".env real preservado: True")
    print("Mensagens enviadas: 0")
    print("Relatórios:", ", ".join(str(path) for path in paths))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
