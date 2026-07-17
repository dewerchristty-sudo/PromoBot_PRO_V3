import unittest
from unittest.mock import patch
from unittest.mock import Mock

from src.core.notifier import Notifier


class NotifierTest(unittest.TestCase):

    def test_sem_alertas_nao_envia(self):

        notifier = Notifier()

        self.assertEqual(
            notifier.send_alerts([]),
            "Nenhum alerta disparado."
        )

    @patch.dict("os.environ", {
        "TELEGRAM_BOT_TOKEN": "",
        "TELEGRAM_CHAT_ID": "",
        "WHATSAPP_WEBHOOK_URL": "",
        "WHATSAPP_PROVIDER": "",
        "ZAPI_INSTANCE_ID": "",
        "ZAPI_INSTANCE_TOKEN": "",
        "ZAPI_CLIENT_TOKEN": "",
        "EVOLUTION_API_URL": "",
        "EVOLUTION_INSTANCE": "",
        "EVOLUTION_API_KEY": "",
        "WHATSAPP_PHONES": "",
    })
    def test_sem_canal_configurado_orienta_notificacao(self):

        notifier = Notifier()

        resultado = notifier.send_alerts([
            {
                "termo": "ssd",
                "preco_alvo": 350.0,
                "loja": "Kabum",
                "preco": "299,90",
                "titulo": "SSD 1TB",
                "link": "https://example.com/ssd",
            }
        ])

        self.assertIn("WhatsApp", resultado)

    def test_formata_alerta_sem_preco_alvo(self):

        notifier = Notifier()

        mensagem = notifier.format_alert({
            "termo": "",
            "preco_alvo": None,
            "loja": "Amazon",
            "preco": "99,90",
            "titulo": "Oferta Fone Bluetooth",
            "link": "https://example.com/fone",
        })

        self.assertIn("Termo: promocoes", mensagem)
        self.assertIn("Tipo: promocao encontrada", mensagem)

    @patch.dict("os.environ", {
        "TELEGRAM_BOT_TOKEN": "token",
        "TELEGRAM_CHAT_ID": "123",
        "WHATSAPP_PROVIDER": "",
        "ZAPI_INSTANCE_ID": "",
        "ZAPI_INSTANCE_TOKEN": "",
        "ZAPI_CLIENT_TOKEN": "",
        "EVOLUTION_API_URL": "",
        "EVOLUTION_INSTANCE": "",
        "EVOLUTION_API_KEY": "",
        "WHATSAPP_WEBHOOK_URL": "",
    })
    @patch("src.core.notifier.requests.post")
    def test_envia_alerta_com_foto_quando_tem_imagem(self, post):

        response = Mock()
        response.raise_for_status.return_value = None
        post.return_value = response

        notifier = Notifier()
        resultado = notifier.send_alerts([
            {
                "termo": "ssd",
                "preco_alvo": 350.0,
                "loja": "Kabum",
                "preco": "299,90",
                "titulo": "SSD 1TB",
                "link": "https://example.com/ssd",
                "imagem": "https://example.com/ssd.jpg",
            }
        ])

        self.assertEqual(resultado, "Enviado por: Telegram")
        self.assertIn("sendPhoto", post.call_args.args[0])

    @patch.dict("os.environ", {
        "TELEGRAM_BOT_TOKEN": "token",
        "TELEGRAM_CHAT_ID": "123",
        "WHATSAPP_PROVIDER": "",
        "ZAPI_INSTANCE_ID": "",
        "ZAPI_INSTANCE_TOKEN": "",
        "ZAPI_CLIENT_TOKEN": "",
        "EVOLUTION_API_URL": "",
        "EVOLUTION_INSTANCE": "",
        "EVOLUTION_API_KEY": "",
        "WHATSAPP_WEBHOOK_URL": "",
    })
    @patch("src.core.notifier.requests.post")
    def test_ignora_alerta_sem_imagem(self, post):

        response = Mock()
        response.raise_for_status.return_value = None
        post.return_value = response

        notifier = Notifier()
        resultado = notifier.send_alerts([
            {
                "termo": "ssd",
                "preco_alvo": 350.0,
                "loja": "Kabum",
                "preco": "299,90",
                "titulo": "SSD 1TB",
                "link": "https://example.com/ssd",
                "imagem": "",
            }
        ])

        self.assertIn("Configure WhatsApp", resultado)
        post.assert_not_called()

    @patch.dict("os.environ", {
        "TELEGRAM_BOT_TOKEN": "",
        "TELEGRAM_CHAT_ID": "",
        "WHATSAPP_PROVIDER": "",
        "ZAPI_INSTANCE_ID": "",
        "ZAPI_INSTANCE_TOKEN": "",
        "ZAPI_CLIENT_TOKEN": "",
        "EVOLUTION_API_URL": "",
        "EVOLUTION_INSTANCE": "",
        "EVOLUTION_API_KEY": "",
        "WHATSAPP_WEBHOOK_URL": "https://example.com/webhook",
        "WHATSAPP_PHONES": "5511999999999",
        "WHATSAPP_TOKEN": "token",
    })
    @patch("src.core.notifier.requests.post")
    def test_envia_alerta_para_whatsapp_com_imagem(self, post):

        response = Mock()
        response.raise_for_status.return_value = None
        post.return_value = response

        notifier = Notifier()
        resultado = notifier.send_alerts([
            {
                "termo": "ssd",
                "preco_alvo": 350.0,
                "loja": "Kabum",
                "preco": "299,90",
                "titulo": "SSD 1TB",
                "link": "https://example.com/ssd",
                "imagem": "https://example.com/ssd.jpg",
            }
        ])

        self.assertEqual(resultado, "Enviado por: WhatsApp")
        self.assertEqual(post.call_args.args[0], "https://example.com/webhook")
        self.assertEqual(
            post.call_args.kwargs["json"]["image_url"],
            "https://example.com/ssd.jpg"
        )

    @patch.dict("os.environ", {
        "TELEGRAM_BOT_TOKEN": "",
        "TELEGRAM_CHAT_ID": "",
        "WHATSAPP_PROVIDER": "zapi",
        "ZAPI_INSTANCE_ID": "instance",
        "ZAPI_INSTANCE_TOKEN": "instance-token",
        "ZAPI_CLIENT_TOKEN": "client-token",
        "WHATSAPP_PHONES": "5511999999999",
        "EVOLUTION_API_URL": "",
        "EVOLUTION_INSTANCE": "",
        "EVOLUTION_API_KEY": "",
    })
    @patch("src.core.notifier.requests.post")
    def test_envia_alerta_para_zapi_com_imagem(self, post):

        response = Mock()
        response.raise_for_status.return_value = None
        post.return_value = response

        notifier = Notifier()
        resultado = notifier.send_alerts([
            {
                "termo": "ssd",
                "preco_alvo": 350.0,
                "loja": "Kabum",
                "preco": "299,90",
                "titulo": "SSD 1TB",
                "link": "https://example.com/ssd",
                "imagem": "https://example.com/ssd.jpg",
            }
        ])

        self.assertEqual(resultado, "Enviado por: WhatsApp")
        self.assertIn("send-image", post.call_args.args[0])
        self.assertEqual(
            post.call_args.kwargs["headers"]["Client-Token"],
            "client-token"
        )
        self.assertEqual(
            post.call_args.kwargs["json"]["image"],
            "https://example.com/ssd.jpg"
        )

    @patch.dict("os.environ", {
        "TELEGRAM_BOT_TOKEN": "",
        "TELEGRAM_CHAT_ID": "",
        "WHATSAPP_PROVIDER": "zapi",
        "ZAPI_INSTANCE_ID": "instance",
        "ZAPI_INSTANCE_TOKEN": "instance-token",
        "ZAPI_CLIENT_TOKEN": "client-token",
        "WHATSAPP_PHONES": "5511999999999,5527997463523",
        "EVOLUTION_API_URL": "",
        "EVOLUTION_INSTANCE": "",
        "EVOLUTION_API_KEY": "",
    })
    @patch("src.core.notifier.requests.post")
    def test_envia_alerta_para_varios_numeros_zapi(self, post):

        response = Mock()
        response.raise_for_status.return_value = None
        post.return_value = response

        notifier = Notifier()
        resultado = notifier.send_alerts([
            {
                "termo": "ssd",
                "preco_alvo": 350.0,
                "loja": "Kabum",
                "preco": "299,90",
                "titulo": "SSD 1TB",
                "link": "https://example.com/ssd",
                "imagem": "https://example.com/ssd.jpg",
            }
        ])

        phones = [
            call.kwargs["json"]["phone"]
            for call in post.call_args_list
        ]

        self.assertEqual(resultado, "Enviado por: WhatsApp")
        self.assertEqual(phones, ["5511999999999", "5527997463523"])

    @patch.dict("os.environ", {
        "TELEGRAM_BOT_TOKEN": "",
        "TELEGRAM_CHAT_ID": "",
        "WHATSAPP_PROVIDER": "evolution",
        "EVOLUTION_API_URL": "http://localhost:8080",
        "EVOLUTION_INSTANCE": "promobot",
        "EVOLUTION_API_KEY": "local-key",
        "WHATSAPP_PHONES": "5511999999999,5527997463523",
        "ZAPI_INSTANCE_ID": "",
        "ZAPI_INSTANCE_TOKEN": "",
        "ZAPI_CLIENT_TOKEN": "",
    })
    @patch("src.core.notifier.requests.post")
    def test_envia_alerta_para_evolution_local(self, post):

        response = Mock()
        response.raise_for_status.return_value = None
        post.return_value = response

        notifier = Notifier()
        resultado = notifier.send_alerts([
            {
                "termo": "ssd",
                "preco_alvo": 350.0,
                "loja": "Kabum",
                "preco": "299,90",
                "titulo": "SSD 1TB",
                "link": "https://example.com/ssd",
                "imagem": "https://example.com/ssd.jpg",
            }
        ])

        phones = [
            call.kwargs["json"]["number"]
            for call in post.call_args_list
        ]

        self.assertEqual(resultado, "Enviado por: WhatsApp")
        self.assertEqual(phones, ["5511999999999", "5527997463523"])
        self.assertEqual(
            post.call_args_list[0].args[0],
            "http://localhost:8080/message/sendMedia/promobot"
        )
        self.assertEqual(
            post.call_args_list[0].kwargs["headers"]["apikey"],
            "local-key"
        )


if __name__ == "__main__":
    unittest.main()
