from pathlib import Path
import os

from src.affiliates.diagnostics import mercado_livre_session_status
from src.stores.mercado_livre_browser import MercadoLivrePersistentContext

from .models import SchedulerValidation


def validate_config(config):
    reasons = []
    if not config.times:
        reasons.append("COLLECTION_TIMES_INVALID")
    if not config.allowed_stores:
        reasons.append("ALLOWED_STORES_MISSING")
    unsupported = set(config.allowed_stores) - {"mercado_livre"}
    if unsupported:
        reasons.append("STORE_NOT_SUPPORTED")
    if config.max_products_per_run < 1:
        reasons.append("MAX_PRODUCTS_INVALID")
    if config.log_level not in {
        "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"
    }:
        reasons.append("LOG_LEVEL_INVALID")
    return SchedulerValidation(
        valid=not reasons,
        status="READY" if not reasons else "CONFIGURATION_INVALID",
        reasons=tuple(reasons),
    )


def operational_preflight(database_path):
    reasons = []
    database_path = Path(database_path)
    try:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        reports = Path("reports/collector_scheduler")
        reports.mkdir(parents=True, exist_ok=True)
    except OSError:
        reasons.append("DIRECTORY_UNAVAILABLE")
    if not MercadoLivrePersistentContext.enabled():
        reasons.append("BROWSER_UNAVAILABLE")
    profile = Path(os.getenv(
        "MERCADO_LIVRE_PROFILE_PATH",
        "data/browser_profiles/mercado_livre",
    ))
    if not profile.exists():
        reasons.append("BROWSER_PROFILE_UNAVAILABLE")
    session = mercado_livre_session_status()
    if session != "SESSION_READY":
        reasons.append(session)
    try:
        import sqlite3
        connection = sqlite3.connect(str(database_path), timeout=5)
        connection.execute("SELECT 1")
        connection.close()
    except Exception:
        reasons.append("DATABASE_UNAVAILABLE")
    return SchedulerValidation(
        valid=not reasons,
        status="READY" if not reasons else "PREFLIGHT_FAILED",
        reasons=tuple(reasons),
    )
