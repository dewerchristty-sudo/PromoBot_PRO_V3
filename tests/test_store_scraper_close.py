import unittest
from unittest.mock import Mock

from src.scraper.store_scraper import StoreScraper


class StoreScraperCloseTest(unittest.TestCase):

    def test_close_sem_pagina_criada(self):
        manager = Mock()
        scraper = StoreScraper(manager)

        scraper.close()

        manager.close.assert_called_once()

    def test_close_com_pagina_valida(self):
        manager = Mock()
        page = Mock()
        scraper = StoreScraper(manager)

        scraper.close(page)

        page.close.assert_called_once()
        manager.close.assert_called_once()

    def test_fechamento_repetido_nao_gera_erro(self):
        manager = Mock()
        page = Mock()
        scraper = StoreScraper(manager)

        scraper.close(page)
        scraper.close(page)
        scraper.close()

        self.assertEqual(page.close.call_count, 2)
        self.assertEqual(manager.close.call_count, 3)

    def test_erro_original_nao_e_substituido_por_erro_de_fechamento(self):
        manager = Mock()
        manager.close.side_effect = RuntimeError("falha no navegador")
        page = Mock()
        page.close.side_effect = RuntimeError("falha na pagina")
        scraper = StoreScraper(manager)

        with self.assertRaisesRegex(ValueError, "erro original"):
            try:
                raise ValueError("erro original")
            finally:
                scraper.close(page)

        page.close.assert_called_once()
        manager.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
