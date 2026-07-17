import unittest

from src.scraper import Parser


class ParserTest(unittest.TestCase):

    def test_limpa_preco(self):

        self.assertEqual(Parser.clean_price("R$ 1.299,90"), "1.299,90")

    def test_converte_preco_para_float(self):

        self.assertEqual(Parser.price_to_float("R$ 1.299,90"), 1299.90)

    def test_corrige_texto_com_acentos_quebrados(self):

        texto = "Upgrade RÃ¡pido com GravaÃ§Ã£o atÃ© 350MB/s â€“ Azul"

        self.assertEqual(
            Parser.clean_text(texto),
            "Upgrade Rápido com Gravação até 350MB/s – Azul"
        )

    def test_link_absoluto_remove_rastreamento(self):

        link = Parser.absolute_link("/produto/123?src=abc", "https://loja.com")
        link = Parser.remove_tracking(link)

        self.assertEqual(link, "https://loja.com/produto/123")


if __name__ == "__main__":
    unittest.main()
