import unittest
from io import BytesIO
from unittest.mock import patch
from unittest.mock import Mock

import requests
from PIL import Image

from src.core.notifier import Notifier


class NotifierTest(unittest.TestCase):

    @staticmethod
    def image_bytes(image_format, size=(600, 600), mode="RGB", color="red"):

        output = BytesIO()
        Image.new(mode, size, color).save(output, format=image_format)
        return output.getvalue()

    @staticmethod
    def image_response(content, content_type):

        response = Mock()
        response.status_code = 200
        response.headers = {
            "Content-Type": content_type,
            "Content-Length": str(len(content)),
        }
        response.iter_content.return_value = [content]
        return response

    @patch("src.core.notifier.requests.get")
    def test_reutiliza_jpeg_valido_sem_recompressao(self, get):

        original = self.image_bytes("JPEG")
        get.return_value = self.image_response(original, "image/jpeg")

        prepared = Notifier().prepare_whatsapp_image("https://example.com/a.jpg")

        self.assertEqual(prepared, original)

    @patch("src.core.notifier.requests.get")
    def test_converte_webp_para_jpeg(self, get):

        get.return_value = self.image_response(
            self.image_bytes("WEBP"),
            "image/webp",
        )

        prepared = Notifier().prepare_whatsapp_image("https://example.com/a.webp")

        self.assertEqual(Image.open(BytesIO(prepared)).format, "JPEG")

    @patch("src.core.notifier.requests.get")
    def test_converte_avif_para_jpeg(self, get):

        get.return_value = self.image_response(
            self.image_bytes("AVIF"),
            "image/avif",
        )

        prepared = Notifier().prepare_whatsapp_image("https://example.com/a.avif")

        self.assertEqual(Image.open(BytesIO(prepared)).format, "JPEG")

    @patch("src.core.notifier.requests.get")
    def test_converte_transparencia_sobre_fundo_branco(self, get):

        source = self.image_bytes("PNG", mode="RGBA", color=(255, 0, 0, 0))
        get.return_value = self.image_response(source, "image/png")

        prepared = Notifier().prepare_whatsapp_image("https://example.com/a.png")
        pixel = Image.open(BytesIO(prepared)).getpixel((300, 300))

        self.assertTrue(all(channel >= 245 for channel in pixel))

    @patch("src.core.notifier.requests.get")
    def test_rejeita_imagem_abaixo_de_500_por_500(self, get):

        source = self.image_bytes("PNG", size=(320, 480))
        get.return_value = self.image_response(source, "image/png")

        with self.assertRaisesRegex(ValueError, "320 x 480"):
            Notifier().prepare_whatsapp_image("https://example.com/pequena.png")

    @patch("src.core.notifier.requests.get")
    def test_rejeita_conteudo_que_nao_e_imagem(self, get):

        get.return_value = self.image_response(b"<html>erro</html>", "text/html")

        with self.assertRaisesRegex(ValueError, "conteudo de imagem"):
            Notifier().prepare_whatsapp_image("https://example.com/erro")

    @patch(
        "src.core.notifier.requests.get",
        side_effect=requests.Timeout("timeout"),
    )
    def test_informa_timeout_no_download(self, _get):

        with self.assertRaisesRegex(ValueError, "tempo limite"):
            Notifier().prepare_whatsapp_image("https://example.com/lenta.jpg")

    @patch("src.core.notifier.requests.get")
    def test_informa_erro_http(self, get):

        response = Mock()
        response.status_code = 403
        response.headers = {}
        get.return_value = response

        with self.assertRaisesRegex(ValueError, "HTTP 403"):
            Notifier().prepare_whatsapp_image("https://example.com/bloqueada.jpg")

    @patch("src.core.notifier.requests.get")
    def test_rejeita_imagem_acima_do_limite(self, get):

        response = Mock()
        response.status_code = 200
        response.headers = {
            "Content-Type": "image/jpeg",
            "Content-Length": str(Notifier.MAX_MANUAL_IMAGE_BYTES + 1),
        }
        get.return_value = response

        with self.assertRaisesRegex(ValueError, "15 MiB"):
            Notifier().prepare_whatsapp_image("https://example.com/grande.jpg")

    @patch.dict("os.environ", {
        "EVOLUTION_API_URL": "http://localhost:8080",
        "EVOLUTION_INSTANCE": "promobot",
        "EVOLUTION_API_KEY": "token",
    }, clear=False)
    @patch("src.core.notifier.requests.post")
    def test_evolution_envia_jpeg_com_multipart(self, post):

        post.return_value.raise_for_status.return_value = None
        content = self.image_bytes("JPEG")

        Notifier().send_evolution_image("Oferta", content, "grupo@g.us")

        kwargs = post.call_args.kwargs
        self.assertEqual(
            set(kwargs["data"]),
            {"number", "mediatype", "caption", "fileName"},
        )
        self.assertEqual(kwargs["data"]["mediatype"], "image")
        self.assertEqual(kwargs["files"]["media"][2], "image/jpeg")
        self.assertNotIn("Content-Type", kwargs["headers"])

    def test_outros_canais_preservam_url_original(self):

        notifier = Notifier()
        notifier.whatsapp_configured = Mock(return_value=True)
        notifier.evolution_configured = Mock(return_value=False)
        notifier.verified_whatsapp_image = Mock(
            return_value="https://example.com/original.webp"
        )
        notifier.whatsapp_recipients_for_alert = Mock(
            return_value=["grupo@g.us"]
        )
        notifier.whatsapp_group_rate_limited = Mock(return_value=False)
        notifier.send_whatsapp_message = Mock(return_value=True)

        notifier.send_whatsapp_alerts([{
            "imagem": "https://example.com/original.webp",
            "imagem_whatsapp": b"jpeg preparado",
        }])

        self.assertEqual(
            notifier.send_whatsapp_message.call_args.args[1],
            "https://example.com/original.webp",
        )

    @patch("src.core.notifier.requests.get")
    def test_imagem_manual_nao_e_substituida_pela_api_shopee(self, get):

        image = "https://example.com/imagem-manual.jpg"
        result = Notifier().verified_whatsapp_image({
            "loja": "Shopee",
            "link": "https://shopee.com.br/produto-i.1.2",
            "imagem": image,
            "imagem_manual": True,
        })

        self.assertEqual(result, image)
        get.assert_not_called()

    @patch("src.core.notifier.requests.get")
    def test_confirma_imagem_da_shopee_pelos_ids_do_anuncio(self, get):

        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "data": {"item": {"image": "foto-oficial-do-produto"}}
        }
        get.return_value = response
        database = Mock()
        notifier = Notifier(database)
        product = {
            "id": 14352,
            "loja": "Shopee",
            "link": "https://shopee.com.br/produto-i.387396391.21230892305",
            "imagem": "https://example.com/foto-errada.jpg",
        }

        image = notifier.verified_whatsapp_image(product)

        self.assertEqual(
            image,
            "https://down-br.img.susercontent.com/file/foto-oficial-do-produto",
        )
        self.assertEqual(
            get.call_args.kwargs["params"],
            {"shop_id": "387396391", "item_id": "21230892305"},
        )
        database.atualizar_imagem_produto.assert_called_once_with(
            14352, image
        )

    @patch("src.core.notifier.requests.get")
    def test_bloqueia_imagem_shopee_quando_nao_consegue_confirmar(self, get):

        get.side_effect = requests.RequestException("indisponivel")
        notifier = Notifier()

        image = notifier.verified_whatsapp_image({
            "loja": "Shopee",
            "link": "https://shopee.com.br/produto-i.1.2",
            "imagem": "https://example.com/foto-possivelmente-errada.jpg",
        })

        self.assertEqual(image, "")

    @patch("src.core.notifier.requests.get")
    def test_aceita_fallback_do_cdn_oficial_da_shopee(self, get):

        api_response = Mock()
        api_response.raise_for_status.side_effect = requests.HTTPError("403")
        cdn_response = Mock()
        cdn_response.raise_for_status.return_value = None
        cdn_response.headers = {"Content-Type": "image/jpeg"}
        get.side_effect = [api_response, cdn_response]
        image = "https://down-br.img.susercontent.com/file/foto-oficial"

        result = Notifier().verified_whatsapp_image({
            "loja": "Shopee",
            "link": "https://shopee.com.br/produto-i.100.200",
            "imagem": image,
        })

        self.assertEqual(result, image)
        cdn_response.close.assert_called_once()

    def test_registra_excecao_humana_sem_interromper_outros_alertas(self):

        database = Mock()
        database.contar_envios_recentes.return_value = 0
        notifier = Notifier(database)
        blocked = {
            "loja": "Amazon",
            "titulo": "Produto sem afiliado",
            "link": "https://www.amazon.com.br/dp/B012345678",
            "imagem": "https://example.com/image.jpg",
        }

        result = notifier.send_alerts([blocked], database)

        self.assertIn("aguardando link afiliado", result)
        database.registrar_pendencias_revisao.assert_called_once()
        args = database.registrar_pendencias_revisao.call_args.args
        self.assertEqual(args[1], "link_afiliado")

    def setUp(self):

        self.notification_stores_patch = patch.dict(
            "os.environ",
            {
                "NOTIFICATION_DISABLED_STORES": "",
                "MAX_OFFER_AGE_HOURS": "0",
                "MIN_DISCOUNT_PERCENT": "0",
                "MAX_NOTIFICATIONS_PER_HOUR": "0",
                "NOTIFICATION_START_HOUR": "0",
                "NOTIFICATION_END_HOUR": "24",
                "MIN_NOTIFICATION_INTERVAL_SECONDS": "0",
                "MAX_NOTIFICATION_INTERVAL_SECONDS": "0",
                "WHATSAPP_GROUPS": "",
                "WHATSAPP_PHONES": "",
                "WHATSAPP_PERSONAL_ALERT_PHONES": "",
                "PERSONAL_ALERT_MIN_DISCOUNT_PERCENT": "60",
                "PERSONAL_ALERT_MAX_DISCOUNT_PERCENT": "90",
                "PERSONAL_ALERT_MIN_SAVINGS": "50",
                "PERSONAL_ALERT_MIN_PRICE": "5",
                "WHATSAPP_GROUP_MAMAE_BEBE": "",
                "WHATSAPP_GROUP_CASA_ENXOVAL": "",
                "WHATSAPP_GROUP_ELETRODOMESTICOS": "",
                "WHATSAPP_GROUP_SMARTPHONES_TECNOLOGIA": "",
                "WHATSAPP_GROUP_BELEZA_PERFUMARIA": "",
                "WHATSAPP_GROUP_LIMPEZA_UTILIDADES": "",
            },
        )
        self.notification_stores_patch.start()

    def tearDown(self):

        self.notification_stores_patch.stop()

    @patch.dict("os.environ", {
        "WHATSAPP_PERSONAL_ALERT_PHONES": "5527996703669",
        "PERSONAL_ALERT_MIN_DISCOUNT_PERCENT": "60",
        "PERSONAL_ALERT_MAX_DISCOUNT_PERCENT": "90",
        "PERSONAL_ALERT_MIN_SAVINGS": "50",
        "PERSONAL_ALERT_MIN_PRICE": "5",
    }, clear=False)
    def test_classifica_oferta_imperdivel_de_qualquer_categoria(self):

        notifier = Notifier()
        self.assertTrue(notifier.is_unmissable_offer({
            "titulo": "Umidificador",
            "preco_valor": 15,
            "maior_preco": 100,
        }))
        self.assertFalse(notifier.is_unmissable_offer({
            "titulo": "Notebook",
            "preco_valor": 2900,
            "maior_preco": 3500,
        }))

    @patch.dict("os.environ", {
        "WHATSAPP_GROUPS": "grupo@g.us",
        "WHATSAPP_PERSONAL_ALERT_PHONES": "5527996703669",
        "PERSONAL_ALERT_MIN_DISCOUNT_PERCENT": "60",
        "PERSONAL_ALERT_MAX_DISCOUNT_PERCENT": "90",
        "PERSONAL_ALERT_MIN_SAVINGS": "50",
        "PERSONAL_ALERT_MIN_PRICE": "5",
    }, clear=False)
    @patch.object(
        Notifier,
        "verified_whatsapp_image",
        return_value="https://example.com/product.jpg",
    )
    def test_oferta_imperdivel_vai_ao_grupo_e_ao_numero_pessoal(
        self, _verified_image
    ):

        notifier = Notifier()
        notifier.whatsapp_configured = Mock(return_value=True)
        notifier.send_whatsapp_message = Mock(return_value=True)
        product = {
            "titulo": "Umidificador",
            "loja": "Shopee",
            "preco_valor": 15,
            "maior_preco": 100,
            "link": "https://shopee.com.br/product/1/2",
            "imagem": "https://example.com/product.jpg",
        }

        self.assertTrue(notifier.send_whatsapp_alerts([product]))
        recipients = [
            call.args[2]
            for call in notifier.send_whatsapp_message.call_args_list
        ]
        self.assertEqual(recipients, ["grupo@g.us", "5527996703669"])
        self.assertIn(
            "OFERTA IMPERDIVEL",
            notifier.send_whatsapp_message.call_args_list[1].args[0],
        )

    def test_sem_alertas_nao_envia(self):

        notifier = Notifier()

        self.assertEqual(
            notifier.send_alerts([]),
            "Nenhum alerta disparado."
        )

    def test_excecao_de_desenvolvimento_ignora_apenas_horario_geral(self):

        notifier = Notifier()
        notifier.within_notification_hours = Mock(return_value=False)
        alert = {
            "loja": "Amazon",
            "link_afiliado_salvo": "https://amzn.to/teste",
            "titulo": "Produto de desenvolvimento",
            "link": "https://example.com/produto",
            "imagem": "https://example.com/produto.jpg",
        }

        blocked = notifier.send_alerts([alert])
        allowed = notifier.send_alerts(
            [alert],
            ignore_notification_hours=True,
        )

        self.assertIn("fora do horario permitido", blocked)
        self.assertNotIn("fora do horario permitido", allowed)

    @patch.dict("os.environ", {
        "WHATSAPP_GROUP_MAMAE_BEBE": "mamae@g.us",
        "WHATSAPP_GROUP_CASA_ENXOVAL": "casa@g.us",
        "WHATSAPP_GROUP_ELETRODOMESTICOS": "eletro@g.us",
        "WHATSAPP_GROUP_SMARTPHONES_TECNOLOGIA": "tech@g.us",
        "WHATSAPP_GROUP_BELEZA_PERFUMARIA": "beleza@g.us",
        "WHATSAPP_GROUP_LIMPEZA_UTILIDADES": "limpeza@g.us",
    }, clear=False)
    def test_separa_produtos_por_grupo_de_whatsapp(self):

        notifier = Notifier()
        examples = {
            "Fralda infantil para bebê": "mamae@g.us",
            "Jogo de cama casal": "casa@g.us",
            "Air fryer digital": "eletro@g.us",
            "Smartphone Galaxy 5G": "tech@g.us",
            "Mini TV portátil recarregável": "tech@g.us",
            "Perfume feminino": "beleza@g.us",
            "Máscara de tratamento capilar": "beleza@g.us",
            "Aspirador para limpeza": "limpeza@g.us",
        }

        for title, expected_group in examples.items():
            self.assertEqual(
                notifier.whatsapp_recipients_for_alert({"titulo": title}),
                [expected_group],
            )

        self.assertEqual(
            notifier.whatsapp_recipients_for_alert({"titulo": "Produto diverso"}),
            [],
        )

        self.assertEqual(
            notifier.whatsapp_recipients_for_alert({
                "titulo": "Produto sem palavra conhecida",
                "categoria_manual": "beleza_perfumaria",
            }),
            ["beleza@g.us"],
        )

    @patch.dict("os.environ", {
        "WHATSAPP_GROUPS": "geral@g.us",
        "WHATSAPP_PHONES": "",
        "WHATSAPP_GROUP_SMARTPHONES_TECNOLOGIA": "tech@g.us",
    }, clear=False)
    def test_grupo_geral_recebe_todas_as_ofertas(self):
        notifier = Notifier()

        self.assertEqual(
            notifier.whatsapp_recipients_for_alert({"titulo": "Smartphone 5G"}),
            ["geral@g.us", "tech@g.us"],
        )
        self.assertEqual(
            notifier.whatsapp_recipients_for_alert({"titulo": "Produto diverso"}),
            ["geral@g.us"],
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
                "loja": "Amazon",
                "link_afiliado_salvo": "https://amzn.to/teste",
                "preco": "299,90",
                "titulo": "SSD 1TB",
                "link": "https://example.com/ssd",
            }
        ])

        self.assertIn("sem imagem valida", resultado)

    def test_formata_alerta_sem_preco_alvo(self):

        notifier = Notifier()

        mensagem = notifier.format_alert({
            "termo": "",
            "preco_alvo": None,
            "loja": "Amazon",
            "preco": "99,90",
            "preco_valor": 99.90,
            "maior_preco": 149.90,
            "titulo": "Oferta Fone Bluetooth",
            "link": "https://example.com/fone",
        })

        self.assertIn(mensagem.splitlines()[0], notifier.ALERT_HEADLINES)
        self.assertIn("\U0001f4f1 Produto:\nOferta Fone Bluetooth", mensagem)
        self.assertIn("\U0001f3ea Loja:\nAmazon", mensagem)
        self.assertIn("\u274c Pre\u00e7o anterior:\nDe: R$ 149,90", mensagem)
        self.assertIn("\u2705 Pre\u00e7o promocional:\nPor: R$ 99,90", mensagem)
        self.assertIn(
            "\U0001f4b0 Voc\u00ea economiza:\nR$ 50,00 \u2014 desconto de 33,4%",
            mensagem,
        )
        self.assertIn("\U0001f6d2 Compre aqui:\nhttps://example.com/fone", mensagem)

    def test_mensagem_manual_exibe_preco_economia_e_desconto(self):

        message = Notifier().format_alert({
            "loja": "Shopee",
            "titulo": "Produto manual",
            "preco": "48,90",
            "preco_valor": 48.90,
            "preco_antigo": "79,90",
            "link": "https://shopee.com.br/produto-i.1.2",
        })

        self.assertIn("De: R$ 79,90", message)
        self.assertIn("Por: R$ 48,90", message)
        self.assertIn("R$ 31,00", message)
        self.assertIn("desconto de 38,8%", message)

    def test_preco_manual_explicito_tem_prioridade_sobre_historico(self):

        message = Notifier().format_alert({
            "loja": "Shopee",
            "titulo": "Produto manual",
            "preco_valor": 44.98,
            "preco_antigo": "79,90",
            "maior_preco": 2290.00,
            "link": "https://shopee.com.br/produto-i.1.2",
        })

        self.assertIn("De: R$ 79,90", message)
        self.assertIn("Por: R$ 44,98", message)
        self.assertIn("R$ 34,92", message)
        self.assertIn("desconto de 43,7%", message)
        self.assertNotIn("R$ 2.290,00", message)

    def test_formata_valor_monetario_com_milhar_pt_br(self):

        self.assertEqual(Notifier().format_money(1299.90), "R$ 1.299,90")

    def test_formata_percentual_usando_historico_do_banco(self):

        database = Mock()
        database.maior_preco_historico.return_value = 120.0
        notifier = Notifier(database)

        mensagem = notifier.format_alert({
            "id": 10,
            "loja": "Amazon",
            "preco": "90,00",
            "preco_valor": 90.0,
            "titulo": "Produto com historico",
            "link": "https://example.com/produto",
        })

        database.maior_preco_historico.assert_called_once_with(
            10,
            "https://example.com/produto",
        )
        self.assertIn("De: R$ 120,00", mensagem)
        self.assertIn("desconto de 25%", mensagem)

    def test_nao_inventa_percentual_sem_preco_de_comparacao(self):

        database = Mock()
        database.maior_preco_historico.return_value = 0
        notifier = Notifier(database)

        mensagem = notifier.format_alert({
            "id": 11,
            "loja": "Amazon",
            "preco": "90,00",
            "preco_valor": 90.0,
            "titulo": "Produto sem historico",
            "link": "https://example.com/produto-sem-historico",
        })

        self.assertNotIn("Preço anterior:", mensagem)
        self.assertNotIn("desconto de", mensagem)

    def test_nao_repete_cabecalho_em_notificacoes_consecutivas(self):

        notifier = Notifier()
        headlines = [notifier.random_headline() for _ in range(30)]

        self.assertEqual(len(set(headlines[:10])), 10)

        for previous, current in zip(headlines, headlines[1:]):
            self.assertNotEqual(previous, current)

    @patch.dict("os.environ", {
        "SHOPEE_AFFILIATE_ID": "18347400316",
        "SHOPEE_AFFILIATE_TEMPLATE": (
            "https://converter.example/?url={url_encoded}&id={affiliate_id}"
        ),
        "SHOPEE_AFFILIATE_STOREFRONT": (
            "https://collshp.com/achadinhos18vivi"
        ),
    })
    def test_formata_link_afiliado_shopee(self):

        mensagem = Notifier().format_alert({
            "termo": "",
            "preco_alvo": None,
            "loja": "Shopee",
            "preco": "21,99",
            "preco_valor": 21.99,
            "titulo": "Fone Bluetooth",
            "link": "https://shopee.com.br/produto-i.1.2",
        })

        self.assertIn(
            "https://converter.example/?url=https%3A%2F%2Fshopee.com.br%2Fproduto-i.1.2&id=18347400316",
            mensagem
        )
        self.assertIn(
            "Mais achadinhos da ViVi na vitrine da Shopee:",
            mensagem,
        )

    @patch.dict("os.environ", {
        "SHOPEE_AFFILIATE_MAP": (
            "bvx75s95=https://s.shopee.com.br/1Vxfk8gpbZ;"
            "19899665250=https://s.shopee.com.br/3g2ANbr3rp"
        ),
    })
    def test_formata_link_afiliado_shopee_por_mapeamento(self):

        notifier = Notifier()

        mensagem_curta = notifier.format_alert({
            "termo": "",
            "preco_alvo": None,
            "loja": "Shopee",
            "preco": "21,99",
            "preco_valor": 21.99,
            "titulo": "Produto Shopee",
            "link": "https://br.shp.ee/bvx75s95?smtt=0.0.9",
        })
        mensagem_item = notifier.format_alert({
            "termo": "",
            "preco_alvo": None,
            "loja": "Shopee",
            "preco": "21,99",
            "preco_valor": 21.99,
            "titulo": "Produto Shopee",
            "link": (
                "https://shopee.com.br/flash_sale"
                "?fromItem=19899665250&promotionId=480859748782201"
            ),
        })

        self.assertIn("https://s.shopee.com.br/1Vxfk8gpbZ", mensagem_curta)
        self.assertIn("https://s.shopee.com.br/3g2ANbr3rp", mensagem_item)

    @patch.dict("os.environ", {
        "MERCADOLIVRE_AFFILIATE_MAP": (
            "MLB111=https://meli.la/outro;"
            "MLB18571345=https://meli.la/2U97MV2"
        ),
    })
    def test_formata_link_afiliado_mercado_livre_por_produto(self):

        mensagem = Notifier().format_alert({
            "termo": "",
            "preco_alvo": None,
            "loja": "Mercado Livre",
            "preco": "129,90",
            "preco_valor": 129.90,
            "titulo": "Memoria RAM Kingston",
            "link": (
                "https://www.mercadolivre.com.br/memoria-ram/p/"
                "MLB18571345"
            ),
        })

        self.assertIn("https://meli.la/2U97MV2", mensagem)
        self.assertNotIn("https://www.mercadolivre.com.br/memoria-ram", mensagem)

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
                "loja": "Amazon",
                "link_afiliado_salvo": "https://amzn.to/teste",
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
        "WHATSAPP_GROUP_MAMAE_BEBE": "grupo-mamae",
        "WHATSAPP_PROVIDER": "",
        "EVOLUTION_API_URL": "",
        "EVOLUTION_INSTANCE": "",
        "EVOLUTION_API_KEY": "",
        "WHATSAPP_WEBHOOK_URL": "",
    })
    @patch("src.core.notifier.requests.post")
    def test_categoria_whatsapp_nao_bloqueia_telegram(self, post):

        response = Mock()
        response.raise_for_status.return_value = None
        post.return_value = response
        notifier = Notifier()

        resultado = notifier.send_alerts([{
            "loja": "Amazon",
                "link_afiliado_salvo": "https://amzn.to/teste",
            "titulo": "Livro de receitas",
            "preco": "49,90",
            "link": "https://example.com/livro",
            "imagem": "https://example.com/livro.jpg",
        }])

        self.assertTrue(resultado.startswith("Enviado por: Telegram"))
        self.assertIn("sem categoria segura", resultado)

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
                "loja": "Amazon",
                "link_afiliado_salvo": "https://amzn.to/teste",
                "preco": "299,90",
                "titulo": "SSD 1TB",
                "link": "https://example.com/ssd",
                "imagem": "",
            }
        ])

        self.assertIn("sem imagem valida", resultado)
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
                "loja": "Amazon",
                "link_afiliado_salvo": "https://amzn.to/teste",
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
                "loja": "Amazon",
                "link_afiliado_salvo": "https://amzn.to/teste",
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
        "WHATSAPP_GROUPS": "",
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
                "loja": "Amazon",
                "link_afiliado_salvo": "https://amzn.to/teste",
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
        "WHATSAPP_GROUPS": "",
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
                "loja": "Amazon",
                "link_afiliado_salvo": "https://amzn.to/teste",
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

    @patch.dict("os.environ", {
        "TELEGRAM_BOT_TOKEN": "",
        "TELEGRAM_CHAT_ID": "",
        "WHATSAPP_PROVIDER": "evolution",
        "EVOLUTION_API_URL": "http://localhost:8080",
        "EVOLUTION_INSTANCE": "promobot",
        "EVOLUTION_API_KEY": "local-key",
        "WHATSAPP_GROUPS": "120363408335461860@g.us",
        "WHATSAPP_PHONES": "",
        "WHATSAPP_PHONE": "",
        "ZAPI_INSTANCE_ID": "",
        "ZAPI_INSTANCE_TOKEN": "",
        "ZAPI_CLIENT_TOKEN": "",
    })
    @patch("src.core.notifier.requests.post")
    def test_envia_alerta_para_grupo_evolution(self, post):

        response = Mock()
        response.raise_for_status.return_value = None
        post.return_value = response

        resultado = Notifier().send_alerts([
            {
                "termo": "fone",
                "preco_alvo": None,
                "loja": "Amazon",
            "link_afiliado_salvo": "https://amzn.to/teste",
                "preco": "21,99",
                "titulo": "Fone Bluetooth",
                "link": "https://example.com/produto",
                "imagem": "https://example.com/fone.jpg",
            }
        ])

        self.assertEqual(resultado, "Enviado por: WhatsApp")
        self.assertEqual(
            post.call_args.kwargs["json"]["number"],
            "120363408335461860@g.us"
        )

    def test_bloqueia_marketplace_sem_link_afiliado(self):

        notifier = Notifier()
        result = notifier.send_alerts([{
            "loja": "Mercado Livre",
            "titulo": "Produto sem afiliado",
            "link": "https://www.mercadolivre.com.br/produto/p/MLB99999999",
            "imagem": "https://example.com/produto.jpg",
        }])

        self.assertIn("aguardando link afiliado", result)

    def test_bloqueia_amazon_sem_link_afiliado(self):

        result = Notifier().send_alerts([{
            "loja": "Amazon",
            "titulo": "Produto Amazon sem afiliado",
            "link": "https://www.amazon.com.br/dp/B012345678",
            "imagem": "https://example.com/produto.jpg",
        }])

        self.assertIn("aguardando link afiliado", result)

    def test_usa_link_afiliado_amazon_salvo(self):

        database = Mock()
        database.buscar_link_afiliado.return_value = "https://amzn.to/abc123"
        notifier = Notifier(database)
        item = {
            "loja": "Amazon",
            "link": "https://www.amazon.com.br/dp/B012345678",
        }

        self.assertTrue(notifier.has_affiliate_link(item))
        self.assertEqual(notifier.affiliate_link(item), "https://amzn.to/abc123")

    @patch.dict("os.environ", {
        "NOTIFICATION_DISABLED_STORES": "Amazon",
    })
    def test_bloqueia_notificacao_de_loja_desabilitada(self):

        result = Notifier().send_alerts([{
            "loja": "Amazon",
            "titulo": "Produto Amazon",
            "link": "https://example.com/produto",
            "imagem": "https://example.com/produto.jpg",
        }])

        self.assertIn("lojas desabilitadas", result)

    @patch.dict("os.environ", {
        "MAX_OFFER_AGE_HOURS": "24",
    })
    def test_bloqueia_oferta_com_mais_de_24_horas(self):

        result = Notifier().send_alerts([{
            "loja": "Amazon",
            "link_afiliado_salvo": "https://amzn.to/teste",
            "titulo": "Oferta antiga",
            "data": "2020-01-01 00:00:00",
            "link": "https://amazon.com.br/produto",
            "imagem": "https://example.com/produto.jpg",
        }])

        self.assertIn("mais de 24 horas", result)

    @patch.dict("os.environ", {
        "MIN_DISCOUNT_PERCENT": "10",
    })
    def test_bloqueia_oferta_abaixo_do_desconto_minimo(self):

        result = Notifier().send_alerts([{
            "loja": "Amazon",
            "link_afiliado_salvo": "https://amzn.to/teste",
            "titulo": "Oferta pequena",
            "preco_valor": 95.0,
            "maior_preco": 100.0,
            "link": "https://amazon.com.br/produto",
            "imagem": "https://example.com/produto.jpg",
        }])

        self.assertIn("abaixo do desconto minimo", result)

    @patch.dict("os.environ", {
        "MAX_NOTIFICATIONS_PER_HOUR": "5",
    })
    def test_respeita_limite_de_notificacoes_por_hora(self):

        database = Mock()
        database.contar_envios_recentes.return_value = 5
        result = Notifier(database).send_alerts([{
            "loja": "Amazon",
            "link_afiliado_salvo": "https://amzn.to/teste",
            "titulo": "Oferta dentro do limite",
            "link": "https://example.com/produto",
            "imagem": "https://example.com/produto.jpg",
        }])

        self.assertIn("aguardando limite horario", result)

    def test_envio_controlado_ignora_horario_mas_exige_protecoes(self):

        database = Mock()
        database.etiqueta_link_afiliado.return_value = "teste"
        notifier = Notifier(database)
        notifier.partition_affiliate_ready = Mock(return_value=([{}], []))
        notifier.whatsapp_recipients_for_alert = Mock(return_value=["grupo@g.us"])
        notifier.whatsapp_configured = Mock(return_value=True)
        notifier.whatsapp_group_rate_limited = Mock(return_value=False)
        notifier.affiliate_link = Mock(return_value="https://meli.la/teste")
        notifier.send_whatsapp_message = Mock(return_value=True)
        item = {
            "loja": "Mercado Livre",
            "titulo": "Produto de teste",
            "link": "https://example.com/produto",
            "imagem": "https://example.com/produto.jpg",
            "preco": "99,90",
        }

        result = notifier.send_test_alert(item)

        self.assertEqual(result, "Teste enviado por WhatsApp para 1 grupo.")
        message = notifier.send_whatsapp_message.call_args.args[0]
        self.assertTrue(message.startswith("\U0001f9ea TESTE CONTROLADO"))
        database.registrar_envio.assert_called_once()
        self.assertEqual(database.registrar_envio.call_args.args[5], "WhatsApp Teste")

    @patch.dict("os.environ", {
        "WHATSAPP_REVIEW_GROUP": "120363411405237640@g.us",
    })
    def test_envio_para_revisao_nao_consume_limite_dos_grupos(self):

        database = Mock()
        database.etiqueta_link_afiliado.return_value = "shopee"
        notifier = Notifier(database)
        notifier.whatsapp_configured = Mock(return_value=True)
        notifier.has_affiliate_link = Mock(return_value=True)
        notifier.affiliate_link = Mock(return_value="https://s.shopee.com.br/teste")
        notifier.verified_whatsapp_image = Mock(
            return_value="https://example.com/produto.jpg"
        )
        notifier.send_whatsapp_message = Mock(return_value=True)
        notifier.whatsapp_group_rate_limited = Mock(
            side_effect=AssertionError("O limite nao deve ser consultado")
        )
        item = {
            "loja": "Shopee",
            "titulo": "Produto para revisao",
            "link": "https://shopee.com.br/produto-i.1.2",
            "imagem": "https://example.com/produto.jpg",
            "preco": "39,90",
        }

        result = notifier.send_review_alert(item)

        self.assertEqual(result, "Oferta enviada para o grupo Revisao PromoBot.")
        notifier.send_whatsapp_message.assert_called_once()
        self.assertEqual(
            notifier.send_whatsapp_message.call_args.args[2],
            "120363411405237640@g.us",
        )
        self.assertEqual(
            database.registrar_envio.call_args.args[5],
            "WhatsApp Revisao",
        )

    @patch.dict("os.environ", {
        "NOTIFICATION_START_HOUR": "23",
        "NOTIFICATION_END_HOUR": "23",
    })
    def test_horarios_iguais_liberam_periodo_integral(self):

        self.assertTrue(Notifier().within_notification_hours())

    def test_prioriza_fila_por_desconto_preco_e_imagem(self):

        items = [
            {
                "titulo": "Sem imagem",
                "preco_valor": 10.0,
                "maior_preco": 100.0,
                "imagem": "",
            },
            {
                "titulo": "Desconto menor",
                "preco_valor": 80.0,
                "maior_preco": 100.0,
                "imagem": "https://example.com/a.jpg",
            },
            {
                "titulo": "Desconto maior preco maior",
                "preco_valor": 70.0,
                "maior_preco": 100.0,
                "imagem": "https://example.com/b.jpg",
            },
            {
                "titulo": "Desconto maior preco menor",
                "preco_valor": 35.0,
                "maior_preco": 50.0,
                "imagem": "https://example.com/c.jpg",
            },
        ]

        prioritized, without_image = Notifier().prioritize_affiliate_queue(items)

        self.assertEqual(
            [item["titulo"] for item in prioritized],
            [
                "Desconto maior preco maior",
                "Desconto maior preco menor",
                "Desconto menor",
            ],
        )
        self.assertEqual(without_image[0]["titulo"], "Sem imagem")

    @patch.dict("os.environ", {
        "TELEGRAM_BOT_TOKEN": "",
        "TELEGRAM_CHAT_ID": "",
        "WHATSAPP_PROVIDER": "evolution",
        "EVOLUTION_API_URL": "http://localhost:8080",
        "EVOLUTION_INSTANCE": "promobot",
        "EVOLUTION_API_KEY": "local-key",
        "WHATSAPP_PHONES": "5511999999999",
        "ZAPI_INSTANCE_ID": "",
        "ZAPI_INSTANCE_TOKEN": "",
        "ZAPI_CLIENT_TOKEN": "",
    })
    @patch("src.core.notifier.requests.post")
    def test_marca_alertas_enviados_quando_envia_com_sucesso(self, post):

        response = Mock()
        response.raise_for_status.return_value = None
        post.return_value = response
        database = Mock()

        alerts = [
            {
                "alerta_id": 1,
                "termo": "",
                "preco_alvo": None,
                "loja": "Amazon",
            "link_afiliado_salvo": "https://amzn.to/teste",
                "preco": "99,90",
                "titulo": "Oferta Fone Bluetooth",
                "link": "https://example.com/fone",
                "imagem": "https://example.com/fone.jpg",
            }
        ]

        resultado = Notifier().send_alerts(alerts, database)

        self.assertEqual(resultado, "Enviado por: WhatsApp")
        database.marcar_notificacoes_enviadas.assert_called_once_with(alerts)

    @patch.dict("os.environ", {
        "TELEGRAM_BOT_TOKEN": "",
        "TELEGRAM_CHAT_ID": "",
        "WHATSAPP_PROVIDER": "evolution",
        "EVOLUTION_API_URL": "http://localhost:8080",
        "EVOLUTION_INSTANCE": "promobot",
        "EVOLUTION_API_KEY": "local-key",
        "WHATSAPP_PHONES": "5511999999999",
    })
    @patch("src.core.notifier.requests.post")
    def test_envio_continua_confirmado_se_historico_falhar(self, post):

        response = Mock()
        response.raise_for_status.return_value = None
        post.return_value = response
        database = Mock()
        database.registrar_envio.side_effect = RuntimeError("banco indisponivel")

        result = Notifier(database).send_alerts([{
            "loja": "Amazon",
            "link_afiliado_salvo": "https://amzn.to/teste",
            "titulo": "Produto enviado",
            "link": "https://example.com/produto",
            "imagem": "https://example.com/produto.jpg",
        }])

        self.assertTrue(result.startswith("Enviado por: WhatsApp"))
        self.assertIn("falha ao registrar historico", result)


if __name__ == "__main__":
    unittest.main()
