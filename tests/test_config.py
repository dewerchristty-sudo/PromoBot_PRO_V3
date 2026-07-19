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


if __name__ == "__main__":
    unittest.main()
