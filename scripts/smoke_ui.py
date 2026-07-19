"""Smoke test seguro das telas principais, sem canais de notificacao reais."""

import os
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Impede que load_dotenv habilite canais reais durante este teste.
for name in (
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "WHATSAPP_PROVIDER",
    "WHATSAPP_WEBHOOK_URL",
    "WHATSAPP_PHONES",
    "WHATSAPP_PHONE",
    "WHATSAPP_GROUPS",
    "EVOLUTION_API_URL",
    "EVOLUTION_INSTANCE",
    "EVOLUTION_API_KEY",
):
    os.environ[name] = ""

from src.database.database import Database
from src.ui.main_window import MainWindow


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="promobot-ui-") as temp_dir:
        database = Database(Path(temp_dir) / "smoke.db")
        window = MainWindow(database)
        window.withdraw()

        pages = (
            window.mostrar_dashboard,
            window.mostrar_busca,
            window.mostrar_produtos,
            window.mostrar_ofertas,
            window.mostrar_alertas,
            window.mostrar_links_afiliados,
            window.mostrar_grupos,
            window.mostrar_monitor,
            window.mostrar_historico,
            window.mostrar_configuracoes,
        )

        try:
            for show_page in pages:
                show_page()
                window.update_idletasks()
                print(f"OK: {show_page.__name__}")
        finally:
            window.fechar()
            database.fechar()


if __name__ == "__main__":
    main()
