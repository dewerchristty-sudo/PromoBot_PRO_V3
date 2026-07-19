import unittest
from unittest.mock import patch
from unittest.mock import Mock

from src.core.notifier import Notifier


class NotifierTest(unittest.TestCase):

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

    def test_sem_alertas_nao_envia(self):

        notifier = Notifier()

        self.assertEqual(
            notifier.send_alerts([]),
            "Nenhum alerta disparado."
        )

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
            "Perfume feminino": "beleza@g.us",
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
        self.assertIn("Mais achadinhos da ViVi na Shopee:", mensagem)

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
            "loja": "Kabum",
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
                "loja": "Loja Teste",
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

    @patch.dict("os.environ", {
        "NOTIFICATION_DISABLED_STORES": "Amazon",
    })
    def test_bloqueia_notificacao_de_loja_desabilitada(self):

        result = Notifier().send_alerts([{
            "loja": "Amazon",
            "titulo": "Produto Amazon",
            "link": "https://amazon.com.br/produto",
            "imagem": "https://example.com/produto.jpg",
        }])

        self.assertIn("lojas desabilitadas", result)

    @patch.dict("os.environ", {
        "MAX_OFFER_AGE_HOURS": "24",
    })
    def test_bloqueia_oferta_com_mais_de_24_horas(self):

        result = Notifier().send_alerts([{
            "loja": "Loja Teste",
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
            "loja": "Loja Teste",
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
            "loja": "Loja Teste",
            "titulo": "Oferta dentro do limite",
            "link": "https://amazon.com.br/produto",
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
                "Desconto maior preco menor",
                "Desconto maior preco maior",
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
                "loja": "Loja Teste",
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
            "loja": "Loja Teste",
            "titulo": "Produto enviado",
            "link": "https://example.com/produto",
            "imagem": "https://example.com/produto.jpg",
        }])

        self.assertTrue(result.startswith("Enviado por: WhatsApp"))
        self.assertIn("falha ao registrar historico", result)


if __name__ == "__main__":
    unittest.main()
