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
            "loja": "Kabum",
            "titulo": "SSD 1TB",
            "preco": "299,90",
            "link": "https://example.com/produto",
            "imagem": "https://example.com/imagem.jpg",
        }

        self.database.salvar_produto(produto)
        self.database.salvar_produto(produto)

        self.assertEqual(self.database.total_produtos(), 1)
        self.assertEqual(self.database.total_coletas_preco(), 2)

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

    def test_atualiza_preco_e_calcula_variacao(self):

        link = "https://example.com/ssd"

        self.database.salvar_produto({
            "loja": "Terabyte",
            "titulo": "SSD 1TB",
            "preco": "500,00",
            "link": link,
            "imagem": "",
        })

        self.database.salvar_produto({
            "loja": "Terabyte",
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

    def test_alerta_dispara_quando_preco_atinge_alvo(self):

        self.database.criar_alerta("SSD", "450,00")

        self.database.salvar_produto({
            "loja": "Kabum",
            "titulo": "SSD 1TB NVMe",
            "preco": "399,90",
            "link": "https://example.com/ssd-alerta",
            "imagem": "",
        })

        disparos = self.database.alertas_disparados()

        self.assertEqual(len(disparos), 1)
        self.assertEqual(disparos[0]["loja"], "Kabum")

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

    def test_cria_e_registra_monitoramento(self):

        primeiro_id = self.database.criar_monitoramento(
            "ssd 1tb",
            30,
            "Amazon,Kabum"
        )

        segundo_id = self.database.criar_monitoramento(
            "SSD 1TB",
            30,
            "Amazon,Kabum"
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
            "Amazon,Kabum"
        )

        monitoramentos = self.database.listar_monitoramentos()

        self.assertGreater(criados, 5)
        self.assertGreater(len(monitoramentos), 5)


if __name__ == "__main__":
    unittest.main()
