import unittest

from src.scraper import Parser


class ParserTest(unittest.TestCase):

    def test_converte_precos_pt_br_para_float(self):

        examples = {
            "44,98": 44.98,
            "R$ 44,98": 44.98,
            "1.299,90": 1299.90,
            "R$ 1.299,90": 1299.90,
        }

        for text, expected in examples.items():
            with self.subTest(text=text):
                self.assertEqual(Parser.price_to_float(text), expected)


if __name__ == "__main__":
    unittest.main()
