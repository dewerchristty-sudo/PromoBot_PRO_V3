import tempfile
import unittest
from pathlib import Path

from src.database import Database


class DatabaseTest(unittest.TestCase):

    def setUp(self):

        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.database = Database(self.db_path)

    def tearDown(self):

        self.database.fechar()
        self.temp_dir.cleanup()

    def test_salva_e_ignora_produto_duplicado(self):

        produto = {
            "loja": "Amazon",
            "titulo": "SSD 1TB",
            "preco": "299,90",
            "link": "https://example.com/produto",
            "imagem": "https://example.com/imagem.jpg",
        }

        self.database.salvar_produto(produto)
        self.database.salvar_produto(produto)

        self.assertEqual(self.database.total_produtos(), 1)
        self.assertEqual(self.database.total_coletas_preco(), 2)

    def test_preco_atual_e_registro_mais_recente_do_historico(self):

        product = {
            "loja": "Shopee",
            "titulo": "Produto manual em promocao",
            "preco": "48,90",
            "preco_antigo": "79,90",
            "link": "https://shopee.com.br/produto-i.1.2",
            "imagem": "https://example.com/produto.jpg",
        }

        self.database.salvar_produto(product)
        saved = self.database.buscar_produto_por_link(product["link"])
        history = self.database.historico_produto(saved["id"])

        self.assertEqual(
            [row["preco_valor"] for row in history[:2]],
            [48.90, 79.90],
        )
        self.assertGreater(history[0]["id"], history[1]["id"])
        self.assertEqual(saved["maior_preco"], 79.90)

    def test_produto_manual_existente_recebe_novo_preco_atual(self):

        link = "https://shopee.com.br/produto-i.10.20"
        self.database.salvar_produto({
            "loja": "Shopee",
            "titulo": "Produto antigo",
            "preco": "2290,00",
            "link": link,
            "imagem": "https://example.com/antiga.jpg",
        })
        self.database.salvar_produto({
            "loja": "Shopee",
            "titulo": "Produto manual",
            "preco": "R$ 44,98",
            "preco_antigo": "R$ 79,90",
            "link": link,
            "imagem": "https://example.com/manual.jpg",
        })

        saved = self.database.buscar_produto_por_link(link)

        self.assertEqual(saved["preco"], "R$ 44,98")
        self.assertEqual(saved["preco_valor"], 44.98)

    def test_preserva_categoria_escolhida_durante_a_pesquisa(self):

        produto = {
            "loja": "Shopee",
            "titulo": "Panela eletrica",
            "preco": "288,39",
            "link": "https://shopee.com.br/produto-i.1.2",
            "imagem": "https://example.com/panela.jpg",
            "categoria_manual": "eletrodomesticos",
        }

        self.database.salvar_produto(produto)
        saved = self.database.buscar_produto_por_link(produto["link"])

        self.assertEqual(saved["categoria_manual"], "eletrodomesticos")

    def test_cria_backup_diario_do_banco(self):

        backups = list((Path(self.temp_dir.name) / "backups").glob("promobot_*.db"))

        self.assertEqual(len(backups), 1)

    def test_redige_segredos_do_backup_de_configuracao(self):

        content = (
            "WHATSAPP_PROVIDER=evolution\n"
            "EVOLUTION_API_KEY=segredo\n"
            "WHATSAPP_GROUPS=grupo@g.us\n"
            "NOTIFICATION_START_HOUR=8\n"
        )

        redacted = Database.redact_env_content(content)

        self.assertIn("WHATSAPP_PROVIDER=evolution", redacted)
        self.assertIn("EVOLUTION_API_KEY=<redacted>", redacted)
        self.assertIn("WHATSAPP_GROUPS=<redacted>", redacted)
        self.assertIn("NOTIFICATION_START_HOUR=8", redacted)
        self.assertNotIn("segredo", redacted)

    def test_verifica_integridade_do_banco(self):

        self.assertEqual(self.database.verificar_integridade(), "ok")

    def test_salva_e_recupera_link_afiliado(self):

        original = "https://www.mercadolivre.com.br/produto/p/MLB65442354"
        affiliate = "https://meli.la/17hf8gS"

        self.database.salvar_link_afiliado(
            "Mercado Livre",
            original,
            affiliate,
        )

        self.assertEqual(
            self.database.buscar_link_afiliado(original),
            affiliate,
        )
        self.assertEqual(self.database.total_links_afiliados(), 1)
        self.assertEqual(
            self.database.etiqueta_link_afiliado(original),
            "promobotwhatsapp",
        )

    def test_busca_produto_pelo_link_para_notificacao_manual(self):

        product = {
            "loja": "Amazon",
            "titulo": "Produto para envio manual",
            "preco": "99,90",
            "link": "https://www.amazon.com.br/dp/B012345678",
            "imagem": "https://example.com/produto.jpg",
        }
        self.database.salvar_produto(product)

        saved = self.database.buscar_produto_por_link(product["link"])

        self.assertIsNotNone(saved)
        self.assertEqual(saved["titulo"], product["titulo"])
        self.assertEqual(saved["imagem"], product["imagem"])
        saved_by_asin = self.database.buscar_produto_por_link(
            "https://amazon.com.br/gp/product/B012345678?tag=promobot-20"
        )
        self.assertIsNotNone(saved_by_asin)
        self.assertEqual(saved_by_asin["id"], saved["id"])
        self.assertIsNone(
            self.database.buscar_produto_por_link("https://example.com/inexistente")
        )

    def test_lista_marketplace_somente_com_ofertas(self):

        produto_ignorado = {
            "loja": "Shopee",
            "titulo": "Oferta que nao sera publicada",
            "preco": "49,90",
            "link": "https://shopee.com.br/produto-ignorado",
            "imagem": "https://example.com/imagem.jpg",
        }
        self.database.salvar_produto(produto_ignorado)
        self.database.ignorar_oferta(produto_ignorado)

        self.assertTrue(
            self.database.oferta_ignorada(produto_ignorado["link"])
        )
        self.assertEqual(self.database.total_ofertas_ignoradas(), 1)
        self.assertEqual(self.database.total_produtos(), 1)

    def test_lista_marketplace_somente_com_ofertas_existentes(self):

        self.database.salvar_produto({
            "loja": "Mercado Livre",
            "titulo": "Produto comum",
            "preco": "100,00",
            "link": "https://mercadolivre.com/produto-comum",
            "imagem": "https://example.com/comum.jpg",
        })
        self.database.salvar_produto({
            "loja": "Mercado Livre",
            "titulo": "Oferta especial com desconto",
            "preco": "80,00",
            "link": "https://mercadolivre.com/produto-oferta",
            "imagem": "https://example.com/oferta.jpg",
        })

        offers = self.database.listar_produtos_marketplace(
            somente_promocoes=True
        )

        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0]["titulo"], "Oferta especial com desconto")

    def test_lista_amazon_na_fila_de_links_afiliados(self):

        self.database.salvar_produto({
            "loja": "Amazon",
            "titulo": "Oferta Amazon com desconto",
            "preco": "79,90",
            "link": "https://www.amazon.com.br/dp/B012345678",
            "imagem": "https://example.com/amazon.jpg",
        })

        products = self.database.listar_produtos_marketplace()

        self.assertEqual(len(products), 1)
        self.assertEqual(products[0]["loja"], "Amazon")

    def test_registra_historico_de_envio(self):

        self.database.registrar_envio(
            "Mercado Livre",
            "Produto afiliado",
            "https://mercadolivre.com.br/p/MLB1",
            "https://meli.la/teste",
            "promobotwhatsapp",
            "WhatsApp",
            "120000@g.us",
        )

        history = self.database.listar_historico_envios()

        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["etiqueta"], "promobotwhatsapp")
        self.assertEqual(history[0]["status"], "enviado")
        self.assertEqual(
            self.database.contar_envios_recentes(60, "WhatsApp"),
            1,
        )

    def test_notificacao_manual_nao_repete_produto(self):

        link = "https://www.mercadolivre.com.br/produto/p/MLB65442354"

        self.assertFalse(self.database.produto_ja_notificado(link))

        self.database.marcar_notificacao_manual(link)
        self.database.marcar_notificacao_manual(link)

        self.assertTrue(self.database.produto_ja_notificado(link))

    def test_bloqueia_titulo_muito_semelhante_ja_enviado(self):

        self.database.registrar_envio(
            "Mercado Livre", "Smartphone Galaxy A55 256GB Preto",
            "https://example.com/a", "https://meli.la/a", "promobotwhatsapp",
            "WhatsApp", "tech@g.us",
        )
        self.assertTrue(self.database.produto_ja_notificado(
            "https://example.com/b", "Mercado Livre",
            "Smartphone Galaxy A55 256 GB Azul",
        ))

    def test_registra_metricas_e_limite_por_destino(self):

        self.database.registrar_envio(
            "Shopee", "Perfume", "original", "afiliado", "etiqueta",
            "WhatsApp", "beleza@g.us",
        )
        self.database.registrar_metricas_grupo("beleza@g.us", 10, 2, 15.5)
        self.assertEqual(
            self.database.contar_envios_destino_recentes("beleza@g.us"), 1
        )
        report = self.database.relatorio_metricas_grupos()
        self.assertEqual(report["beleza@g.us"]["vendas"], 2)

    def test_fila_de_notificacoes_sobrevive_e_pode_ser_recuperada(self):

        alert = {
            "link": "https://example.com/oferta",
            "loja": "Shopee",
            "titulo": "Oferta com falha temporária",
            "preco_valor": 20.0,
        }
        self.database.enfileirar_notificacoes([alert], "sem conexão")
        queued = self.database.listar_fila_notificacoes()
        self.assertEqual(self.database.total_fila_notificacoes(), 1)
        self.assertEqual(queued[0][1]["titulo"], alert["titulo"])
        self.database.remover_fila_notificacoes([queued[0][0]["id"]])
        self.assertEqual(self.database.total_fila_notificacoes(), 0)

    def test_pendencia_de_revisao_sobrevive_e_pode_ser_resolvida(self):

        alert = {
            "link": "https://example.com/revisao",
            "loja": "Amazon",
            "titulo": "Produto aguardando categoria",
        }
        self.database.registrar_pendencias_revisao(
            [alert], "categoria", "Categoria nao identificada."
        )
        pending = self.database.listar_pendencias_revisao()
        self.assertEqual(self.database.total_pendencias_revisao(), 1)
        self.assertEqual(pending[0][1]["titulo"], alert["titulo"])

        self.database.resolver_pendencias_por_chaves([alert["link"]])

        self.assertEqual(self.database.total_pendencias_revisao(), 0)
        self.assertEqual(
            self.database.listar_pendencias_revisao("resolvida")[0][0]["status"],
            "resolvida",
        )

    def test_registra_eventos_do_supervisor(self):

        self.database.registrar_evento_sistema(
            "alerta", "whatsapp", "desconectado"
        )
        events = self.database.listar_eventos_sistema()
        self.assertEqual(events[0]["componente"], "whatsapp")

    def test_busca_produtos_por_titulo(self):

        self.database.salvar_produto({
            "loja": "Amazon",
            "titulo": "Mouse Gamer",
            "preco": "99,90",
            "link": "https://example.com/mouse",
            "imagem": "",
        })

        resultados = self.database.buscar_produtos("mouse")

        self.assertEqual(len(resultados), 1)
        self.assertEqual(resultados[0]["loja"], "Amazon")

    def test_produto_coletado_novamente_volta_ao_topo(self):

        antigo = {
            "loja": "Amazon", "titulo": "Produto pesquisado novamente",
            "preco": "99,90", "link": "https://example.com/antigo",
            "imagem": "",
        }
        outro = {
            "loja": "Shopee", "titulo": "Outro produto",
            "preco": "89,90", "link": "https://example.com/outro",
            "imagem": "",
        }
        self.database.salvar_produto(antigo)
        self.database.salvar_produto(outro)
        self.database.cursor.execute(
            "UPDATE produtos SET data = '2020-01-01 00:00:00' WHERE link = ?",
            (antigo["link"],),
        )
        self.database.cursor.execute(
            "UPDATE produtos SET data = '2025-01-01 00:00:00' WHERE link = ?",
            (outro["link"],),
        )
        self.database.conn.commit()

        self.database.salvar_produto(antigo)
        resultados = self.database.buscar_produtos(ordenar="recentes")

        self.assertEqual(resultados[0]["link"], antigo["link"])

    def test_atualiza_preco_e_calcula_variacao(self):

        link = "https://example.com/ssd"

        self.database.salvar_produto({
            "loja": "Shopee",
            "titulo": "SSD 1TB",
            "preco": "500,00",
            "link": link,
            "imagem": "",
        })

        self.database.salvar_produto({
            "loja": "Shopee",
            "titulo": "SSD 1TB",
            "preco": "400,00",
            "link": link,
            "imagem": "",
        })

        produtos = self.database.buscar_produtos("ssd")
        ofertas = self.database.ofertas_com_variacao()

        self.assertEqual(self.database.total_produtos(), 1)
        self.assertEqual(self.database.total_coletas_preco(), 2)
        self.assertEqual(produtos[0]["preco_valor"], 400.0)
        self.assertEqual(ofertas[0]["maior_preco"], 500.0)

    def test_produto_novo_nao_e_oferta_sem_historico(self):

        self.database.salvar_produto({
            "loja": "Amazon",
            "titulo": "SSD 1TB NVMe",
            "preco": "500,00",
            "link": "https://example.com/ssd-novo",
            "imagem": "",
        })

        self.assertEqual(self.database.ofertas_com_variacao(), [])

    def test_variacao_inferior_a_cinco_porcento_nao_e_oferta(self):

        produto = {
            "loja": "Amazon",
            "titulo": "SSD 1TB NVMe",
            "preco": "500,00",
            "link": "https://example.com/ssd-variacao-pequena",
            "imagem": "",
        }
        self.database.salvar_produto(produto)
        produto["preco"] = "480,00"
        self.database.salvar_produto(produto)

        self.assertEqual(self.database.ofertas_com_variacao(), [])

    def test_alerta_dispara_quando_preco_atinge_alvo(self):

        self.database.criar_alerta("SSD", "450,00")

        self.database.salvar_produto({
            "loja": "Amazon",
            "titulo": "SSD 1TB NVMe",
            "preco": "500,00",
            "link": "https://example.com/ssd-alerta",
            "imagem": "",
        })

        self.database.salvar_produto({
            "loja": "Amazon",
            "titulo": "SSD 1TB NVMe",
            "preco": "399,90",
            "link": "https://example.com/ssd-alerta",
            "imagem": "",
        })

        disparos = self.database.alertas_disparados()

        self.assertEqual(len(disparos), 1)
        self.assertEqual(disparos[0]["loja"], "Amazon")
        self.assertEqual(disparos[0]["maior_preco"], 500.0)

    def test_alerta_sem_preco_dispara_somente_promocoes(self):

        self.database.criar_alerta("", "")

        self.database.salvar_produto({
            "loja": "Amazon",
            "titulo": "Oferta imperdivel Fone Bluetooth",
            "preco": "99,90",
            "link": "https://example.com/fone-oferta",
            "imagem": "",
        })

        self.database.salvar_produto({
            "loja": "Amazon",
            "titulo": "Fone Bluetooth preco normal",
            "preco": "199,90",
            "link": "https://example.com/fone-normal",
            "imagem": "",
        })

        disparos = self.database.alertas_disparados()

        self.assertEqual(len(disparos), 1)
        self.assertEqual(disparos[0]["titulo"], "Oferta imperdivel Fone Bluetooth")
        self.assertIsNone(disparos[0]["preco_alvo"])

    def test_alertas_pendentes_nao_repetem_notificacao(self):

        self.database.criar_alerta("", "")

        self.database.salvar_produto({
            "loja": "Amazon",
            "titulo": "Oferta imperdivel Fone Bluetooth",
            "preco": "99,90",
            "link": "https://example.com/fone-oferta",
            "imagem": "",
        })

        pendentes = self.database.alertas_pendentes()

        self.assertEqual(len(pendentes), 1)

        self.database.marcar_notificacoes_enviadas(pendentes)

        self.assertEqual(len(self.database.alertas_pendentes()), 0)

    def test_mesmo_produto_nao_repete_em_alertas_diferentes(self):

        self.database.criar_alerta("Fone", "150,00")
        self.database.criar_alerta("Bluetooth", "150,00")
        self.database.salvar_produto({
            "loja": "Mercado Livre",
            "titulo": "Fone Bluetooth em oferta",
            "preco": "99,90",
            "link": "https://example.com/fone-unico",
            "imagem": "https://example.com/fone.jpg",
        })

        pendentes = self.database.alertas_pendentes()

        self.assertEqual(len(pendentes), 1)
        self.database.marcar_notificacoes_enviadas(pendentes)
        self.assertEqual(len(self.database.alertas_pendentes()), 0)

    def test_alertas_pendentes_nao_repetem_mesmo_produto_com_link_diferente(self):

        self.database.criar_alerta("", "")

        self.database.salvar_produto({
            "loja": "Amazon",
            "titulo": "Oferta imperdivel Fone Bluetooth",
            "preco": "99,90",
            "link": "https://example.com/fone-oferta?utm=1",
            "imagem": "",
        })

        pendentes = self.database.alertas_pendentes()

        self.assertEqual(len(pendentes), 1)

        self.database.marcar_notificacoes_enviadas(pendentes)

        self.database.salvar_produto({
            "loja": "Amazon",
            "titulo": "Oferta imperdivel Fone Bluetooth",
            "preco": "99,90",
            "link": "https://example.com/fone-oferta?utm=2",
            "imagem": "",
        })

        self.assertEqual(len(self.database.alertas_pendentes()), 0)

    def test_alertas_pendentes_nao_repetem_titulo_com_acento_maiusculo(self):

        self.database.criar_alerta("", "")

        self.database.salvar_produto({
            "loja": "Amazon",
            "titulo": "Oferta CÁLCULOS TRABALHISTAS",
            "preco": "99,90",
            "link": "https://example.com/calculo?ref=1",
            "imagem": "",
        })

        pendentes = self.database.alertas_pendentes()

        self.assertEqual(len(pendentes), 1)

        self.database.marcar_notificacoes_enviadas(pendentes)

        self.database.salvar_produto({
            "loja": "Amazon",
            "titulo": "Oferta CÁLCULOS TRABALHISTAS",
            "preco": "99,90",
            "link": "https://example.com/calculo?ref=2",
            "imagem": "",
        })

        self.assertEqual(len(self.database.alertas_pendentes()), 0)

    def test_cria_e_registra_monitoramento(self):

        primeiro_id = self.database.criar_monitoramento(
            "ssd 1tb",
            30,
            "Amazon,Amazon"
        )

        segundo_id = self.database.criar_monitoramento(
            "SSD 1TB",
            30,
            "Amazon,Amazon"
        )

        monitoramentos = self.database.listar_monitoramentos()

        self.assertEqual(len(monitoramentos), 1)
        self.assertEqual(primeiro_id, segundo_id)
        self.assertEqual(monitoramentos[0]["termo"], "ssd 1tb")

        self.database.registrar_execucao_monitoramento(
            monitoramentos[0]["id"],
            40
        )

        atualizado = self.database.listar_monitoramentos()[0]

        self.assertEqual(atualizado["ultimo_total"], 40)

    def test_cria_monitoramentos_padrao(self):

        criados = self.database.criar_monitoramentos_padrao(
            60,
            "Amazon,Amazon"
        )

        monitoramentos = self.database.listar_monitoramentos()

        self.assertGreater(criados, 5)
        self.assertGreater(len(monitoramentos), 5)


if __name__ == "__main__":
    unittest.main()
