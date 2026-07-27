from bs4 import BeautifulSoup
from unittest.mock import Mock, patch
import unittest

from src.stores.mercado_livre import (
    MercadoLivre,
    MercadoLivreBlockedError,
)
from src.core.store_manager import StoreManager
from src.offers.models import OfferCandidate


def card(
    title="SSD 1TB",
    fraction="1.299",
    cents="90",
    href="/ssd-1tb/p/MLB123456",
    image="https://http2.mlstatic.com/item.webp",
    previous=False,
):
    old = """
      <s><span class="andes-money-amount andes-money-amount--previous">
        <span class="andes-money-amount__fraction">1.999</span>
      </span></s>
    """ if previous else ""
    cent_html = (
        f'<span class="andes-money-amount__cents">{cents}</span>'
        if cents is not None else ""
    )
    return f"""
    <li class="ui-search-layout__item">
      <a class="poly-component__title" href="{href}">{title}</a>
      {old}
      <div class="poly-price__current">
        <span class="andes-money-amount">
          <span class="andes-money-amount__fraction">{fraction}</span>
          {cent_html}
        </span>
      </div>
      <img data-src="{image}">
    </li>
    """


class MercadoLivreCollectionTest(unittest.TestCase):

    def setUp(self):
        self.store = MercadoLivre.__new__(MercadoLivre)

    def cards(self, html):
        soup = BeautifulSoup(html, "lxml")
        return self.store.find_cards(soup)[0]

    def test_seletor_principal_e_formato_store_manager(self):
        result = self.store.parse_cards(self.cards(card()))[0]
        self.assertEqual(set(result), {
            "loja", "titulo", "preco", "link", "imagem"
        })
        self.assertEqual(result["loja"], "Mercado Livre")
        self.assertEqual(result["preco"], "1.299,90")
        sanitized = StoreManager(enabled_stores=[]).sanitize_results([result])
        self.assertEqual(len(sanitized), 1)
        candidate = OfferCandidate.from_mapping(result)
        self.assertEqual(candidate.store, "Mercado Livre")
        self.assertEqual(candidate.title, "SSD 1TB")

    def test_seletor_alternativo_poly_card(self):
        html = card().replace(
            '<li class="ui-search-layout__item">',
            '<div class="andes-card poly-card">',
        ).replace("</li>", "</div>")
        cards, counts = self.store.find_cards(
            BeautifulSoup(html, "lxml")
        )
        self.assertEqual(counts["div.poly-card"], 1)
        self.assertEqual(len(self.store.parse_cards(cards)), 1)

    def test_fallback_por_link_de_produto(self):
        html = card().replace(
            'class="ui-search-layout__item"', 'class="resultado-novo"'
        )
        cards, counts = self.store.find_cards(
            BeautifulSoup(html, "lxml")
        )
        self.assertGreater(counts["a.poly-component__title[href]"], 0)
        self.assertEqual(len(self.store.parse_cards(cards)), 1)

    def test_preco_sem_centavos(self):
        result = self.store.parse_cards(
            self.cards(card(cents=None))
        )[0]
        self.assertEqual(result["preco"], "1.299")

    def test_preco_principal_nao_confunde_anterior(self):
        result = self.store.parse_cards(
            self.cards(card(previous=True))
        )[0]
        self.assertEqual(result["preco"], "1.299,90")

    def test_titulo_preco_ou_link_ausente_rejeita_card(self):
        samples = (
            card(title="").replace(">SSD 1TB<", "><"),
            card(fraction="").replace(
                '<span class="andes-money-amount__fraction"></span>', ""
            ),
            card(href="https://example.com/banner"),
        )
        for html in samples:
            with self.subTest(html=html[:50]):
                self.assertEqual(
                    self.store.parse_cards(self.cards(html)), []
                )

    def test_link_relativo_vira_absoluto(self):
        result = self.store.parse_cards(self.cards(card()))[0]
        self.assertEqual(
            result["link"],
            "https://www.mercadolivre.com.br/ssd-1tb/p/MLB123456",
        )

    def test_link_patrocinado_com_wid_vira_produto_direto(self):
        href = (
            "https://www.mercadolivre.com.br/navigation/recos?"
            "ad_domain=VIPCORE&wid=MLB4580504787"
        )
        result = self.store.parse_cards(
            self.cards(card(href=href))
        )[0]
        self.assertEqual(
            result["link"],
            "https://produto.mercadolivre.com.br/MLB-4580504787",
        )

    def test_produtos_duplicados_sao_removidos(self):
        results = self.store.parse_cards(self.cards(card() + card()))
        self.assertEqual(len(results), 1)

    def test_imagem_e_opcional(self):
        results = self.store.parse_cards(
            self.cards(card(image=""))
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["imagem"], "")

    def test_pagina_sem_produtos_e_sem_bloqueio(self):
        cards, counts = self.store.find_cards(
            BeautifulSoup("<html><h1>Sem resultados</h1></html>", "lxml")
        )
        self.assertEqual(cards, [])
        self.assertTrue(all(value == 0 for value in counts.values()))

    def test_detecta_captcha_e_pagina_de_seguranca(self):
        self.assertEqual(
            self.store.block_reason(
                "https://mercadolivre.com.br/gz/account-verification",
                "Mercado Libre",
                "<p>Verifique sua conta</p>",
            ),
            "account-verification",
        )
        self.assertEqual(
            self.store.block_reason("", "", "<div>captcha</div>"),
            "captcha",
        )

    def test_search_transforma_bloqueio_em_falha_controlada(self):
        page = Mock()
        page.goto.return_value.status = 200
        page.url = (
            "https://www.mercadolivre.com.br/gz/account-verification"
        )
        page.title.return_value = "Mercado Libre"
        page.content.return_value = "<html>account-verification</html>"
        manager = Mock()
        manager.new_page.return_value = page
        store = MercadoLivre(manager)
        with patch.object(store, "save_diagnostic"):
            with self.assertRaises(MercadoLivreBlockedError):
                store.search("ssd 1tb")
        page.close.assert_called_once()
        manager.close.assert_called_once()

    def test_falha_de_rede_e_timeout_sao_propagados_sem_travar_fechamento(self):
        for error in (RuntimeError("rede"), TimeoutError("timeout")):
            page = Mock()
            page.goto.side_effect = error
            manager = Mock()
            manager.new_page.return_value = page
            with self.subTest(error=error):
                with self.assertRaises(type(error)):
                    MercadoLivre(manager).search("ssd 1tb")
                page.close.assert_called_once()
                manager.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
