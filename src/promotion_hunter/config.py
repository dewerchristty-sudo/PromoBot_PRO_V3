"""Configurações operacionais do Promotion Hunter Automático."""
from __future__ import annotations

import os
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