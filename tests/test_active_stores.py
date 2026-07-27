from pathlib import Path
import tempfile
import unittest

from src.core.notifier import Notifier
from src.core.store_manager import StoreManager
from src.database.offer_pipeline_repository import OfferPipelineRepository
from src.offers.pipeline import OfferPipeline
from src.offers.price_history_dashboard import PriceHistoryDashboard
from src.offers.models import PriceObservation
from src.stores.active import ACTIVE_STORE_NAMES, is_active_store


class ActiveStoresPolicyTest(unittest.TestCase):

    def test_somente_tres_lojas_sao_registradas(self):
        self.assertEqual(
            tuple(store.name for store in StoreManager().stores),
            ACTIVE_STORE_NAMES,
        )
        self.assertEqual(
            StoreManager.default_store_names(),
            list(ACTIVE_STORE_NAMES),
        )
        self.assertEqual(StoreManager.experimental_store_names(), [])

    def test_pacote_nao_contem_modulos_de_outras_lojas(self):
        store_files = {
            path.name for path in Path("src/stores").glob("*.py")
        }
        self.assertEqual(store_files, {
            "__init__.py",
            "active.py",
            "base_store.py",
            "mercado_livre.py",
            "mercado_livre_browser.py",
            "amazon.py",
            "shopee.py",
        })

    def test_store_manager_ignora_nome_inativo_solicitado(self):
        manager = StoreManager(enabled_stores=[
            "Amazon", "Loja legada"
        ])
        self.assertEqual(
            [store.name for store in manager.stores], ["Amazon"]
        )

    def test_pipeline_ignora_produto_legado(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = OfferPipelineRepository(
                Path(directory) / "shadow.db"
            )
            repository.migrate()
            try:
                result = OfferPipeline(repository).process_batch([
                    {
                        "loja": "Loja legada",
                        "titulo": "Produto antigo",
                        "preco": "100,00",
                        "link": "https://example.com/antigo",
                        "imagem": "https://example.com/antigo.jpg",
                    },
                    {
                        "loja": "Amazon",
                        "titulo": "Produto atual",
                        "preco": "100,00",
                        "link": "https://example.com/atual",
                        "imagem": "https://example.com/atual.jpg",
                    },
                ])
                self.assertEqual(result.metrics.received_count, 1)
                self.assertEqual(
                    result.items[0].analysis.candidate.store, "Amazon"
                )
            finally:
                repository.close()

    def test_historico_legado_nao_entra_nos_indicadores(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = OfferPipelineRepository(
                Path(directory) / "shadow.db"
            )
            repository.migrate()
            try:
                repository.add(PriceObservation(
                    "legacy", 10, repository.now(),
                    store="Loja legada",
                ))
                repository.add(PriceObservation(
                    "active", 20, repository.now(),
                    store="Shopee",
                ))
                snapshot = PriceHistoryDashboard(repository).snapshot()
                self.assertEqual(snapshot["products_monitored"], 1)
                self.assertEqual(snapshot["lowest_price"], 20)
            finally:
                repository.close()

    def test_notifier_recusa_loja_inativa_antes_do_transporte(self):
        notifier = Notifier()
        self.assertEqual(
            notifier.send_alerts([{
                "loja": "Loja legada",
                "titulo": "Produto",
                "link": "https://example.com/produto",
            }]),
            "Nenhum alerta disparado.",
        )

    def test_nomes_ativos_normalizados(self):
        self.assertTrue(is_active_store("mercado livre"))
        self.assertTrue(is_active_store("AMAZON"))
        self.assertTrue(is_active_store("Shopee"))
        self.assertFalse(is_active_store("Loja legada"))


if __name__ == "__main__":
    unittest.main()
