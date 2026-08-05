"""Configurações operacionais do Promotion Hunter Automático."""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Final

# =====================================================================
# Modo de operação
# =====================================================================
SCHEDULER_ENABLED: Final[bool] = os.getenv(
    "PROMOTION_HUNTER_SCHEDULER_ENABLED", "false"
).strip().casefold() in {"1", "true", "yes", "on"}

# =====================================================================
# Timezone
# =====================================================================
from zoneinfo import ZoneInfo
OPERATIONAL_TIMEZONE: Final[ZoneInfo] = ZoneInfo("America/Sao_Paulo")
ALLOWED_START_HOUR: Final[int] = 8
ALLOWED_END_HOUR: Final[int] = 22

# =====================================================================
# Intervalos
# =====================================================================
INTERVAL_MINUTES: Final[int] = int(os.getenv(
    "PROMOTION_HUNTER_INTERVAL_MINUTES", "30"
))
MIN_SECONDS_BETWEEN_MESSAGES: Final[int] = int(os.getenv(
    "PROMOTION_HUNTER_MIN_SECONDS_BETWEEN_MESSAGES", "600"
))

# =====================================================================
# Limites de mensagens
# =====================================================================
MAX_MESSAGES_PER_RUN: Final[int] = int(os.getenv(
    "PROMOTION_HUNTER_MAX_MESSAGES_PER_RUN", "1"
))
MAX_MESSAGES_PER_HOUR: Final[int] = int(os.getenv(
    "PROMOTION_HUNTER_MAX_MESSAGES_PER_HOUR", "2"
))
MAX_MESSAGES_PER_DAY: Final[int] = int(os.getenv(
    "PROMOTION_HUNTER_MAX_MESSAGES_PER_DAY", "8"
))

ACCELERATED_MODE_KEY: Final[str] = "promotion_hunter_accelerated_mode"
ACCELERATED_INTERVAL_MINUTES: Final[int] = 2
ACCELERATED_MAX_MESSAGES_PER_RUN: Final[int] = 10
ACCELERATED_MIN_SECONDS_BETWEEN_MESSAGES: Final[int] = 3


@dataclass(frozen=True)
class HunterOperationalSettings:
    """Os três ajustes de ritmo; nenhuma regra de segurança é alterada."""

    accelerated: bool = False
    interval_minutes: int = INTERVAL_MINUTES
    max_messages_per_run: int = MAX_MESSAGES_PER_RUN
    min_seconds_between_messages: int = MIN_SECONDS_BETWEEN_MESSAGES


def accelerated_mode_enabled(database_path=None):
    """Lê a preferência existente sem criar banco, tabela ou schema."""
    env = os.getenv("PROMOTION_HUNTER_ACCELERATED_MODE")
    if env is not None:
        return env.strip().casefold() in {"1", "true", "yes", "on"}
    path = Path(database_path or ("promobot" + ".db"))
    if not path.exists():
        return False
    try:
        uri = f"file:{path.resolve().as_posix()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as connection:
            row = connection.execute(
                "SELECT valor FROM configuracoes_app WHERE chave=? LIMIT 1",
                (ACCELERATED_MODE_KEY,),
            ).fetchone()
    except (sqlite3.Error, OSError):
        return False
    return bool(row) and str(row[0]).strip().casefold() in {
        "1", "true", "yes", "on",
    }


def operational_settings(database_path=None):
    enabled = accelerated_mode_enabled(database_path)
    if enabled:
        return HunterOperationalSettings(
            accelerated=True,
            interval_minutes=ACCELERATED_INTERVAL_MINUTES,
            max_messages_per_run=ACCELERATED_MAX_MESSAGES_PER_RUN,
            min_seconds_between_messages=(
                ACCELERATED_MIN_SECONDS_BETWEEN_MESSAGES
            ),
        )
    return HunterOperationalSettings()

# =====================================================================
# Cooldown e retry
# =====================================================================
PRODUCT_COOLDOWN_HOURS: Final[int] = int(os.getenv(
    "PROMOTION_HUNTER_PRODUCT_COOLDOWN_HOURS", "72"
))
MAX_DELIVERY_ATTEMPTS: Final[int] = int(os.getenv(
    "PROMOTION_HUNTER_MAX_DELIVERY_ATTEMPTS", "3"
))
MAX_CONSECUTIVE_FAILURES: Final[int] = int(os.getenv(
    "PROMOTION_HUNTER_MAX_CONSECUTIVE_FAILURES", "3"
))
FAILURE_COOLDOWN_MINUTES: Final[int] = int(os.getenv(
    "PROMOTION_HUNTER_FAILURE_COOLDOWN_MINUTES", "60"
))
SENDING_TIMEOUT_MINUTES: Final[int] = int(os.getenv(
    "PROMOTION_HUNTER_SENDING_TIMEOUT_MINUTES", "15"
))

# =====================================================================
# Termos de busca (Mercado Livre)
# =====================================================================
DEFAULT_SEARCH_TERMS: Final[tuple[str, ...]] = (
    "celular",
    "notebook",
    "smart tv",
    "fone bluetooth",
    "air fryer",
    "caixa de som",
    "smartwatch",
)

# =====================================================================
# Destinos de teste
# =====================================================================
def test_destinations():
    raw = os.getenv("PROMOTION_HUNTER_DESTINATIONS", "")
    if not raw.strip():
        return ()
    return tuple(
        dest.strip()
        for dest in raw.replace(";", ",").split(",")
        if dest.strip()
    )
