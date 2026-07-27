from pathlib import Path
from unittest.mock import Mock
import unittest

from scripts.setup_mercado_livre_profile import (
    close_auxiliary_blank_tabs,
    mercado_livre_tab,
)


def tab(url):
    page = Mock()
    page.url = url
    page.is_closed.return_value = False
    return page


class MercadoLivreProfileSetupTest(unittest.TestCase):

    def test_fecha_about_blank_auxiliar_e_mantem_mercado_livre(self):
        blank = tab("about:blank")
        mercado = tab("https://www.mercadolivre.com.br/login")
        context = Mock()
        context.pages = [blank, mercado]
        close_auxiliary_blank_tabs(context, mercado)
        blank.close.assert_called_once()
        mercado.close.assert_not_called()

    def test_seleciona_ultima_aba_valida_do_mercado_livre(self):
        original = tab("https://www.mercadolivre.com.br/")
        popup = tab("https://www.mercadolivre.com.br/login")
        other = tab("https://example.com/")
        context = Mock()
        context.pages = [original, other, popup]
        selected = mercado_livre_tab(context, original)
        self.assertIs(selected, popup)
        popup.bring_to_front.assert_called_once()

    def test_setup_nao_pausa_nao_abre_devtools_e_nao_guarda_segredos(self):
        source = Path(
            "scripts/setup_mercado_livre_profile.py"
        ).read_text(encoding="utf-8").casefold()
        self.assertNotIn(".pause(", source)
        self.assertNotIn("devtools=true", source)
        self.assertNotIn("password=", source)
        self.assertNotIn("senha=", source)
        self.assertNotIn("cookie", source)
        self.assertNotIn("token=", source)


if __name__ == "__main__":
    unittest.main()
