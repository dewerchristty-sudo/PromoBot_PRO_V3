from pathlib import Path
import tempfile
from unittest.mock import Mock, patch
import unittest

from src.stores.mercado_livre import MercadoLivre
from src.stores.mercado_livre_browser import MercadoLivrePersistentContext


class FakePlaywrightFactory:
    def __init__(self):
        self.playwright = Mock()
        self.context = Mock()
        self.page = Mock()
        self.context.new_page.return_value = self.page
        self.playwright.chromium.launch_persistent_context.return_value = (
            self.context
        )

    def __call__(self):
        starter = Mock()
        starter.start.return_value = self.playwright
        return starter


class MercadoLivrePersistentProfileTest(unittest.TestCase):

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "profile"
        self.factory = FakePlaywrightFactory()

    def tearDown(self):
        self.tempdir.cleanup()

    def session(self):
        return MercadoLivrePersistentContext(
            self.path, headless=False,
            playwright_factory=self.factory,
        )

    def test_cria_perfil_e_contexto_persistente(self):
        session = self.session()
        page = session.new_page()
        self.assertTrue(self.path.is_dir())
        self.assertTrue(session.profile_created)
        self.assertFalse(session.profile_reused)
        self.assertIs(page, self.factory.page)
        kwargs = (
            self.factory.playwright.chromium
            .launch_persistent_context.call_args.kwargs
        )
        self.assertEqual(kwargs["user_data_dir"], str(self.path.resolve()))
        self.assertFalse(kwargs["headless"])
        session.close()

    def test_reutiliza_perfil_existente(self):
        self.path.mkdir(parents=True)
        (self.path / "Preferences").write_text("{}", encoding="utf-8")
        session = self.session()
        session.start()
        self.assertTrue(session.profile_reused)
        self.assertFalse(session.profile_created)
        session.close()

    def test_pasta_ausente_e_criada(self):
        self.assertFalse(self.path.exists())
        session = self.session()
        session.start()
        self.assertTrue(self.path.exists())
        session.close()

    def test_caminho_invalido_e_rejeitado(self):
        self.path.write_text("arquivo", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "não é uma pasta"):
            self.session().start()

    def test_contexto_e_playwright_fechados_corretamente(self):
        session = self.session()
        session.start()
        session.close()
        self.factory.context.close.assert_called_once()
        self.factory.playwright.stop.assert_called_once()
        self.assertIsNone(session.context)
        self.assertIsNone(session.playwright)

    def test_mercado_livre_usa_perfil_sem_mudar_outras_lojas(self):
        with patch.dict("os.environ", {
            "MERCADO_LIVRE_PERSISTENT_PROFILE_ENABLED": "True",
            "MERCADO_LIVRE_PROFILE_PATH": str(self.path),
        }):
            store = MercadoLivre()
        self.assertIsInstance(
            store.browser_manager, MercadoLivrePersistentContext
        )
        from src.stores.amazon import Amazon
        amazon = Amazon()
        self.assertNotIsInstance(
            amazon.browser_manager, MercadoLivrePersistentContext
        )
        amazon.browser_manager.close()

    def test_perfil_pode_ser_desligado_sem_quebrar_compatibilidade(self):
        with patch.dict("os.environ", {
            "MERCADO_LIVRE_PERSISTENT_PROFILE_ENABLED": "False",
        }):
            store = MercadoLivre()
        from src.core.browser_manager import BrowserManager
        self.assertIsInstance(store.browser_manager, BrowserManager)

    def test_sessao_valida_expirada_account_verification_e_captcha(self):
        self.assertEqual(
            MercadoLivre.block_reason(
                "https://lista.mercadolivre.com.br/ssd-1tb",
                "SSD 1TB", "<li class='ui-search-layout__item'>x</li>",
            ),
            "",
        )
        for html, expected in (
            ("account-verification", "account-verification"),
            ("captcha", "captcha"),
            ("access denied", "access denied"),
        ):
            with self.subTest(expected=expected):
                self.assertEqual(
                    MercadoLivre.block_reason("", "", html), expected
                )

    def test_codigo_nao_contem_senha_cookie_ou_token_em_logs(self):
        source = Path(
            "src/stores/mercado_livre_browser.py"
        ).read_text(encoding="utf-8").casefold()
        forbidden_writes = (
            "print(cookie", "logger.info(cookie", "password=",
            "senha=", "token=",
        )
        self.assertFalse(any(item in source for item in forbidden_writes))


if __name__ == "__main__":
    unittest.main()
