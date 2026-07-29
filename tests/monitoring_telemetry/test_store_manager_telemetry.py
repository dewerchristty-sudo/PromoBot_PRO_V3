import unittest
from unittest.mock import Mock

from src.core.store_manager import StoreManager


def product(identifier, *, title="Produto"):
    return {
        "loja": "Loja Teste",
        "titulo": title,
        "preco": "99,90",
        "link": f"https://example.com/{identifier}",
        "imagem": "https://example.com/image.jpg",
    }


class FakeStore:
    name = "Loja Teste"

    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error

    def search(self, _term):
        if self.error:
            raise self.error
        return self.result


class StoreManagerTelemetryTest(unittest.TestCase):

    @staticmethod
    def manager(store, observer=None):
        manager = StoreManager(
            enabled_stores=[],
            offer_shadow_enabled=False,
            telemetry_observer=observer,
        )
        manager.stores = [store]
        return manager

    def test_enabled_and_disabled_telemetry_return_same_products(self):
        products = [product(1), product(2)]
        without = self.manager(FakeStore(products)).search_all("produto")
        observer = Mock()
        with_telemetry = self.manager(
            FakeStore(products),
            observer,
        ).search_all("produto")
        self.assertEqual(without, with_telemetry)
        observer.record_store.assert_called_once()

    def test_records_returned_sanitized_and_aggregate_counts(self):
        observer = Mock()
        invalid = {"loja": "", "titulo": "", "link": "", "preco": ""}
        result = self.manager(
            FakeStore([product(1), invalid]),
            observer,
        ).search_all("produto")
        self.assertEqual(len(result), 1)
        values = observer.record_store.call_args.kwargs
        self.assertEqual(values["returned_count"], 2)
        self.assertEqual(values["sanitized_count"], 1)
        self.assertEqual(values["aggregate_added_count"], 1)
        self.assertEqual(values["status"], "success")

    def test_zero_results_is_explicit(self):
        observer = Mock()
        result = self.manager(FakeStore([]), observer).search_all("produto")
        self.assertEqual(result, [])
        values = observer.record_store.call_args.kwargs
        self.assertEqual(values["status"], "zero_results")
        self.assertEqual(values["error_type"], "zero_results")

    def test_total_sanitization_is_explicit(self):
        observer = Mock()
        invalid = {"loja": "", "titulo": "", "link": "", "preco": ""}
        self.manager(FakeStore([invalid]), observer).search_all("produto")
        values = observer.record_store.call_args.kwargs
        self.assertEqual(values["returned_count"], 1)
        self.assertEqual(values["sanitized_count"], 0)
        self.assertEqual(values["status"], "sanitization_total")

    def test_store_exception_is_preserved_and_observed(self):
        observer = Mock()
        result = self.manager(
            FakeStore(error=RuntimeError("HTTP 503")),
            observer,
        ).search_all("produto")
        self.assertEqual(result, [])
        values = observer.record_store.call_args.kwargs
        self.assertEqual(values["status"], "error")
        self.assertIsInstance(values["error"], RuntimeError)

    def test_telemetry_failure_does_not_change_collection(self):
        observer = Mock()
        observer.record_store.side_effect = RuntimeError("telemetry offline")
        result = self.manager(
            FakeStore([product(1)]),
            observer,
        ).search_all("produto")
        self.assertEqual(result, [product(1)])


if __name__ == "__main__":
    unittest.main()
