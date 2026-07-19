"""
Validação e gerenciamento de configurações do PromoBot
"""

import os
from pathlib import Path
from dotenv import load_dotenv


class ConfigValidator:
    """Validador de configurações e variáveis de ambiente"""

    REQUIRED_TELEGRAM_FIELDS = ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]
    REQUIRED_WHATSAPP_FIELDS = ["WHATSAPP_PROVIDER"]

    @staticmethod
    def load_env(env_path: str = ".env") -> None:
        """Carrega variáveis de ambiente do arquivo .env"""
        if Path(env_path).exists():
            load_dotenv(env_path)

    @staticmethod
    def validate_notification_config() -> dict:
        """
        Valida configurações de notificação.
        Retorna dict com status de cada canal.
        """
        config_status = {
            "telegram": False,
            "whatsapp": False,
            "webhooks": False,
        }

        # Validar Telegram
        telegram_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

        if telegram_token and telegram_chat_id:
            config_status["telegram"] = True

        # Validar WhatsApp
        whatsapp_provider = os.getenv("WHATSAPP_PROVIDER", "").strip()
        whatsapp_phones = os.getenv("WHATSAPP_PHONES", "").strip()
        whatsapp_groups = os.getenv("WHATSAPP_GROUPS", "").strip()

        if whatsapp_provider and (whatsapp_phones or whatsapp_groups):
            config_status["whatsapp"] = True

        # Validar Webhooks (mais genéricos)
        webhook_url = os.getenv("WEBHOOK_URL", "").strip()

        if webhook_url:
            config_status["webhooks"] = True

        return config_status

    @staticmethod
    def get_config_summary() -> str:
        """Retorna um resumo da configuração atual"""
        config_status = ConfigValidator.validate_notification_config()

        summary = (
            f"[CONFIG] Telegram: {'✓' if config_status['telegram'] else '✗'} | "
            f"WhatsApp: {'✓' if config_status['whatsapp'] else '✗'} | "
            f"Webhooks: {'✓' if config_status['webhooks'] else '✗'}"
        )

        return summary

    @staticmethod
    def validate_evolution_api() -> bool:
        """Valida se Evolution API está configurada"""
        evolution_url = os.getenv("EVOLUTION_API_URL", "").strip()
        evolution_key = os.getenv("EVOLUTION_API_KEY", "").strip()

        return bool(evolution_url and evolution_key)
