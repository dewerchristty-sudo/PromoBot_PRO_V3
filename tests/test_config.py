import os
import unittest
from unittest.mock import patch

from src.config import ConfigValidator


class ConfigValidatorTest(unittest.TestCase):

    @patch.dict(
        os.environ,
        {
            "TELEGRAM_BOT_TOKEN": "token",
            "TELEGRAM_CHAT_ID": "chat",
            "WHATSAPP_PROVIDER": "evolution",
            "WHATSAPP_PHONES": "",
            "WHATSAPP_GROUPS": "120363000000000000@g.us",
            "WEBHOOK_URL": "",
        },
        clear=True,
    )
    def test_reconhece_telegram_e_whatsapp_somente_com_grupo(self):

        status = ConfigValidator.validate_notification_config()

        self.assertTrue(status["telegram"])
        self.assertTrue(status["whatsapp"])
        self.assertFalse(status["webhooks"])

    @patch.dict(
        os.environ,
        {
            "WHATSAPP_PROVIDER": "evolution",
            "WHATSAPP_PHONES": "",
            "WHATSAPP_GROUPS": "",
            "WHATSAPP_GROUP_SMARTPHONES_TECNOLOGIA": (
                "120363000000000000@g.us"
            ),
        },
        clear=True,
    )
    def test_reconhece_whatsapp_com_grupo_por_categoria(self):

        status = ConfigValidator.validate_notification_config()

        self.assertTrue(status["whatsapp"])

    @patch("src.config.load_dotenv")
    @patch.dict(os.environ, {"ENABLE_DEV_MODE": "True"}, clear=True)
    def test_habilita_modo_de_desenvolvimento(self, _load_dotenv):

        self.assertTrue(ConfigValidator.dev_mode_enabled())

    @patch("src.config.load_dotenv")
    @patch.dict(os.environ, {"ENABLE_DEV_MODE": "False"}, clear=True)
    def test_modo_de_desenvolvimento_fica_desabilitado_por_padrao(
        self,
        _load_dotenv,
    ):

        self.assertFalse(ConfigValidator.dev_mode_enabled())


if __name__ == "__main__":
    unittest.main()
