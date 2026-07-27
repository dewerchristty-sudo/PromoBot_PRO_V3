import unittest

from src.offers import OfferCandidate, OfferIdentity


class OfferIdentityTest(unittest.TestCase):

    def setUp(self):
        self.identity = OfferIdentity()

    def identify(self, title, **changes):
        return self.identity.identify(OfferCandidate(
            title=title,
            store=changes.pop("store", "Amazon"),
            current_price=changes.pop("current_price", 100),
            **changes,
        ))

    def test_mesmo_produto_com_titulos_diferentes(self):
        titles = (
            "SSD Kingston NV3 1TB NVMe",
            "Kingston NV3 SSD NVMe 1 TB",
            "SSD M.2 NVMe Kingston NV3 1000GB",
        )
        signatures = {self.identify(title).signature for title in titles}
        self.assertEqual(len(signatures), 1)

    def test_acentos_pontuacao_e_promocao_nao_alteram_identidade(self):
        first = self.identify("Fone Áudio Pro, Preto!")
        second = self.identify(
            "OFERTA: Fone Audio Pro Preto - frete grátis"
        )
        self.assertEqual(first.signature, second.signature)

    def test_1000gb_1024gb_e_1tb_sao_equivalentes(self):
        signatures = {
            self.identify(f"SSD Kingston NV3 {capacity}").signature
            for capacity in ("1000GB", "1024 GB", "1 TB")
        }
        self.assertEqual(len(signatures), 1)

    def test_nvme_com_caixa_diferente_e_equivalente(self):
        self.assertEqual(
            self.identify("SSD NVME Kingston NV3 1TB").signature,
            self.identify("ssd NVMe kingston nv3 1tb").signature,
        )

    def test_capacidades_diferentes_nao_sao_iguais(self):
        self.assertNotEqual(
            self.identify("SSD Kingston NV3 1TB").signature,
            self.identify("SSD Kingston NV3 2TB").signature,
        )

    def test_modelos_diferentes_nao_sao_iguais(self):
        self.assertNotEqual(
            self.identify("SSD Kingston NV3 1TB").signature,
            self.identify("SSD Kingston KC3000 1TB").signature,
        )

    def test_mesmo_link_e_identidade_deterministica(self):
        candidate = OfferCandidate(
            title="Produto Teste",
            product_link="https://example.com/item/1?utm_source=x",
        )
        first = self.identity.identify(candidate)
        second = self.identity.identify(candidate)
        self.assertEqual(first.signature, second.signature)
        self.assertEqual(first.link_signature, second.link_signature)

    def test_cor_importante_e_preservada(self):
        self.assertNotEqual(
            self.identify("Mouse Logitech MX Preto").signature,
            self.identify("Mouse Logitech MX Branco").signature,
        )


if __name__ == "__main__":
    unittest.main()
