import base64
import io
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from src.core.whatsapp_control import WhatsAppControl


class WhatsAppControlTest(unittest.TestCase):

    @patch.dict("os.environ", {"EVOLUTION_API_URL": "http://evolution", "EVOLUTION_INSTANCE": "promobot", "EVOLUTION_API_KEY": "secret"})
    @patch("src.core.whatsapp_control.requests.get")
    def test_reconhece_whatsapp_conectado(self, get):
        get.return_value = Mock(status_code=200)
        get.return_value.raise_for_status = Mock()
        get.return_value.json.return_value = {"instance": {"state": "open"}}
        self.assertEqual(WhatsAppControl().connect_whatsapp(), ("connected", None))

    def test_converte_qr_code_base64_em_imagem(self):
        source = Image.new("RGB", (2, 2), "white")
        buffer = io.BytesIO()
        source.save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode()
        result = WhatsAppControl._qr_image({"qrcode": {"base64": f"data:image/png;base64,{encoded}"}})
        self.assertEqual(result.size, (2, 2))

    @patch.dict("os.environ", {"EVOLUTION_INSTANCE": "", "EVOLUTION_API_KEY": ""}, clear=False)
    def test_exige_configuracao_da_evolution(self):
        with self.assertRaisesRegex(RuntimeError, "EVOLUTION_INSTANCE"):
            WhatsAppControl._evolution_settings()


if __name__ == "__main__":
    unittest.main()
