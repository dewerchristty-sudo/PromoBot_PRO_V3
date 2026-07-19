"""
Constantes e configurações centralizadas do PromoBot
"""

# ============================================
# TIMEOUTS (em milissegundos)
# ============================================

TIMEOUT_PAGE_LOAD = 90000      # Timeout para carregar página
TIMEOUT_NETWORK_IDLE = 60000   # Timeout para rede ficar inativa
TIMEOUT_WAIT_DEFAULT = 5000    # Aguardar genérico
TIMEOUT_WAIT_MEDIUM = 15000    # Aguardar médio (Shopee)
TIMEOUT_WAIT_SHORT = 3000      # Aguardar curto

# ============================================
# BROWSER SETTINGS
# ============================================

BROWSER_VIEWPORT_WIDTH = 1366
BROWSER_VIEWPORT_HEIGHT = 768
BROWSER_TIMEZONE = "America/Sao_Paulo"
BROWSER_LOCALE = "pt-BR"
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/138.0.0.0 Safari/537.36"
)

# ============================================
# DATABASE
# ============================================

DB_DEFAULT_NAME = "promobot.db"
DB_BACKUP_PREFIX = "promobot_"
DB_CONFIG_BACKUP_PREFIX = "promobot_env_"

# ============================================
# MONITORING
# ============================================

MONITOR_DEFAULT_INTERVAL = 30  # minutos
MONITOR_HEALTH_CHECK_INTERVAL = 30  # segundos

# ============================================
# UI
# ============================================

WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 720
WINDOW_MIN_WIDTH = 1100
WINDOW_MIN_HEIGHT = 650

# ============================================
# SCRAPING
# ============================================

SEARCH_RESULTS_LIMIT = 20
SHOPEE_RESULTS_LIMIT = 40
SEARCH_DELAY_MIN = 1  # segundos entre buscas
