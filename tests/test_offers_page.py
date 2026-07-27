import unittest

from src.ui.offers_page import OffersPage


class OffersPageTest(unittest.TestCase):

    def test_filtra_por_preco_e_desconto_e_ordena_melhores(self):

        offers = [
            {
                "id": 1,
                "preco_valor": 80.0,
                "maior_preco": 100.0,
                "coletas": 5,
            },
            {
                "id": 2,
                "preco_valor": 50.0,
                "maior_preco": 100.0,
                "coletas": 2,
            },
            {
                "id": 3,
                "preco_valor": 250.0,
                "maior_preco": 500.0,
                "coletas": 8,
            },
            {
                "id": 4,
                "preco_valor": 95.0,
                "maior_preco": 100.0,
                "coletas": 10,
            },
        ]

        ranked = OffersPage.filter_and_rank(
            offers,
            max_price=200,
            min_discount=10,
        )

        self.assertEqual([item[1]["id"] for item in ranked], [2, 1])
        self.assertEqual(ranked[0][0], 50.0)

    def test_parse_filtro_aceita_valor_brasileiro(self):

        self.assertEqual(OffersPage.parse_filter("1.200,50", 200), 1200.50)
        self.assertEqual(OffersPage.parse_filter("invalido", 200), 200.0)

    def test_todos_os_grupos_possuem_chave_de_destino(self):

        self.assertEqual(OffersPage.CATEGORY_LABELS["Automatico"], "")
        self.assertEqual(
            set(value for value in OffersPage.CATEGORY_LABELS.values() if value),
            {
                "mamae_bebe",
                "casa_enxoval",
                "eletrodomesticos",
                "smartphones_tecnologia",
                "beleza_perfumaria",
                "limpeza_utilidades",
            },
        )


if __name__ == "__main__":
    unittest.main()
