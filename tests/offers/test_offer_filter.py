import unittest

from src.offers import OfferCandidate, OfferFilter, OfferFilterPolicy


class OfferFilterTest(unittest.TestCase):

    def candidate(self, **changes):
        values = {
            "title": "Produto",
            "store": "Amazon",
            "category": "Tecnologia",
            "current_price": 80.0,
            "previous_price": 100.0,
            "image_url": "https://example.com/image.jpg",
            "affiliate_link": "https://example.com/affiliate",
        }
        values.update(changes)
        return OfferCandidate(**values)

    def test_preco_zero_e_negativo_sao_invalidos(self):
        for price in (0, -1):
            with self.subTest(price=price):
                result = OfferFilter().analyze(
                    self.candidate(current_price=price)
                )
                self.assertFalse(result.approved)
                self.assertIn("preco_invalido", result.reasons)

    def test_link_afiliado_ausente_e_bloqueio_operacional(self):
        result = OfferFilter().analyze(self.candidate(affiliate_link=""))
        self.assertTrue(result.approved)
        self.assertIn("link_afiliado_ausente", result.operational_blocks)

    def test_imagem_ausente_e_bloqueio_operacional(self):
        result = OfferFilter().analyze(self.candidate(image_url=""))
        self.assertTrue(result.approved)
        self.assertIn("imagem_ausente", result.operational_blocks)

    def test_loja_nao_permitida(self):
        offer_filter = OfferFilter(OfferFilterPolicy(
            allowed_stores=("Amazon", "Amazon"),
        ))
        result = offer_filter.analyze(self.candidate(store="Loja desconhecida"))
        self.assertFalse(result.approved)
        self.assertIn("loja_nao_permitida", result.reasons)

    def test_categoria_preco_desconto_e_duplicidade(self):
        offer_filter = OfferFilter(OfferFilterPolicy(
            minimum_price=50,
            maximum_price=500,
            minimum_discount=30,
            allowed_categories=("Tecnologia",),
        ))
        result = offer_filter.analyze(self.candidate(
            current_price=40,
            previous_price=50,
            category="Outros",
            duplicate=True,
        ))
        self.assertFalse(result.approved)
        self.assertIn("abaixo_do_preco_minimo", result.reasons)
        self.assertIn("abaixo_do_desconto_minimo", result.reasons)
        self.assertIn("categoria_nao_permitida", result.reasons)
        self.assertIn("produto_duplicado", result.reasons)

    def test_desconto_acima_de_noventa_marca_dados_suspeitos(self):
        result = OfferFilter().analyze(self.candidate(
            current_price=5,
            previous_price=100,
        ))
        self.assertFalse(result.approved)
        self.assertIn("dados_suspeitos", result.reasons)
        self.assertIn(
            "desconto_acima_de_90_porcento",
            result.warnings,
        )

    def test_modo_sombra_nunca_bloqueia_fluxo_atual(self):
        result = OfferFilter().analyze(self.candidate(
            current_price=0,
            image_url="",
            affiliate_link="",
        ))
        self.assertTrue(result.shadow_mode)
        self.assertFalse(result.blocks_current_flow)


if __name__ == "__main__":
    unittest.main()
