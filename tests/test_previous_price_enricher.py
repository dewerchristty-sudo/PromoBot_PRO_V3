"""Testes controlados para o PreviousPriceEnricher."""

import time
import sqlite3
import pytest
from unittest.mock import MagicMock, patch

from src.promotion_hunter.previous_price_enricher import (
    PreviousPriceEnricher,
    ENRICH_TIMEOUT_SECONDS,
    MAX_ENRICHMENTS_PER_CYCLE,
    CACHE_TTL_SECONDS,
)


class TestPreviousPriceEnricherUnit:
    """Testes unitarios do enricher (sem chamadas reais ao Mercado Livre)."""

    def test_enrich_ignores_non_mercado_livre(self):
        enricher = PreviousPriceEnricher()
        product = {"loja": "Amazon", "current_price": 100, "product_url": "https://amazon.com/p/123"}
        result = enricher.enrich(product)
        assert result is product
        assert "previous_price" not in result

    def test_enrich_ignores_already_enriched(self):
        enricher = PreviousPriceEnricher()
        product = {
            "loja": "Mercado Livre",
            "current_price": 100,
            "previous_price": 150,  # já tem preço anterior válido
            "product_url": "https://mercadolivre.com.br/MLB-123",
        }
        result = enricher.enrich(product)
        assert result["previous_price"] == 150
        assert enricher._enrich_count == 0  # não contou porque já tinha

    def test_enrich_ignores_missing_url(self):
        enricher = PreviousPriceEnricher()
        product = {"loja": "Mercado Livre", "current_price": 100}
        result = enricher.enrich(product)
        assert result is product
        assert enricher._enrich_count == 0

    def test_enrich_ignores_zero_current_price(self):
        enricher = PreviousPriceEnricher()
        product = {"loja": "Mercado Livre", "current_price": 0, "product_url": "https://mercadolivre.com.br/MLB-123"}
        result = enricher.enrich(product)
        assert result is product
        assert enricher._enrich_count == 0

    def test_cache_prevents_duplicate_enrichment(self):
        """Produto já enriquecido (no cache) não é enriquecido novamente."""
        enricher = PreviousPriceEnricher(max_per_cycle=5)
        url = "https://mercadolivre.com.br/MLB-123"

        # Mock product_from_url
        with patch.object(PreviousPriceEnricher, "_get_store") as mock_get_store:
            mock_store = MagicMock()
            mock_store.product_from_url.return_value = {"preco_antigo": "R$ 299,90"}
            mock_get_store.return_value = mock_store

            # Primeiro enriquecimento
            p1 = {"loja": "Mercado Livre", "current_price": 199.90, "product_url": url}
            result1 = enricher.enrich(p1)
            assert result1["previous_price"] == 299.90
            assert result1["savings"] == 100.00
            assert result1["discount_percent"] == 33.34
            assert enricher._enrich_count == 1

            # Segundo enriquecimento (mesmo URL) - deve usar cache, não visitar
            p2 = {"loja": "Mercado Livre", "current_price": 199.90, "product_url": url}
            result2 = enricher.enrich(p2)
            assert result2["previous_price"] == 299.90
            assert result2["savings"] == 100.00
            assert enricher._enrich_count == 1  # NÃO incrementou (cache)

            # Verifica que product_from_url foi chamado apenas 1 vez
            assert mock_store.product_from_url.call_count == 1

    def test_cache_negative_result(self):
        """URLs sem preço anterior também entram no cache (resultado negativo)."""
        enricher = PreviousPriceEnricher(max_per_cycle=5)
        url = "https://mercadolivre.com.br/MLB-999"

        with patch.object(PreviousPriceEnricher, "_get_store") as mock_get_store:
            mock_store = MagicMock()
            mock_store.product_from_url.return_value = {}  # sem preco_antigo
            mock_get_store.return_value = mock_store

            p1 = {"loja": "Mercado Livre", "current_price": 199.90, "product_url": url}
            result1 = enricher.enrich(p1)
            assert "previous_price" not in result1
            assert enricher._enrich_count == 1

            # Segunda chamada - NÃO deve visitar novamente
            p2 = {"loja": "Mercado Livre", "current_price": 199.90, "product_url": url}
            result2 = enricher.enrich(p2)
            assert "previous_price" not in result2
            assert enricher._enrich_count == 1  # cache negativo
            assert mock_store.product_from_url.call_count == 1

    def test_limit_per_cycle(self):
        """Respeita limite maximo de enriquecimentos por ciclo."""
        enricher = PreviousPriceEnricher(max_per_cycle=3)

        with patch.object(PreviousPriceEnricher, "_get_store") as mock_get_store:
            mock_store = MagicMock()
            mock_store.product_from_url.return_value = {"preco_antigo": "R$ 500,00"}
            mock_get_store.return_value = mock_store

            for i in range(10):
                product = {
                    "loja": "Mercado Livre",
                    "current_price": 300,
                    "product_url": f"https://mercadolivre.com.br/MLB-{i}",
                }
                enricher.enrich(product)

            # Apenas 3 chamadas reais
            assert enricher._enrich_count == 3
            assert mock_store.product_from_url.call_count == 3

    def test_enrich_handles_store_error_gracefully(self):
        """Falha no enriquecimento NAO interrompe o ciclo."""
        enricher = PreviousPriceEnricher(max_per_cycle=5)

        with patch.object(PreviousPriceEnricher, "_get_store") as mock_get_store:
            mock_store = MagicMock()
            mock_store.product_from_url.side_effect = RuntimeError("Timeout")
            mock_get_store.return_value = mock_store

            product = {
                "loja": "Mercado Livre",
                "current_price": 100,
                "product_url": "https://mercadolivre.com.br/MLB-fail",
            }
            result = enricher.enrich(product)
            # Retorna o produto inalterado
            assert result is product
            assert "previous_price" not in result

    def test_enrich_rejects_previous_price_not_greater_than_current(self):
        """So aceita previous_price > current_price."""
        enricher = PreviousPriceEnricher()

        with patch.object(PreviousPriceEnricher, "_get_store") as mock_get_store:
            mock_store = MagicMock()
            # preco_antigo = 100, current = 150 -> nao e desconto real
            mock_store.product_from_url.return_value = {"preco_antigo": "R$ 100,00"}
            mock_get_store.return_value = mock_store

            product = {
                "loja": "Mercado Livre",
                "current_price": 150,
                "product_url": "https://mercadolivre.com.br/MLB-456",
            }
            result = enricher.enrich(product)
            assert "previous_price" not in result

    def test_parse_price_handles_formats(self):
        """Testa parse de diferentes formatos de preco."""
        cases = [
            ("R$ 1.234,56", 1234.56),
            ("R$ 99,90", 99.90),
            ("R$ 1500", 1500.0),
            ("1.299,99", 1299.99),
            ("299.90", 299.90),
            (199.90, 199.90),
            (0, None),
            ("", None),
            (None, None),
        ]
        for input_val, expected in cases:
            result = PreviousPriceEnricher._parse_price(input_val)
            if expected is None:
                assert result is None, f"Expected None for {input_val!r}, got {result!r}"
            else:
                assert result == expected, f"Expected {expected} for {input_val!r}, got {result!r}"

    def test__apply_sets_fields(self):
        """_apply calcula savings e discount_percent."""
        product = {"loja": "Mercado Livre", "current_price": 199.90}
        result = PreviousPriceEnricher._apply(product, 299.90, 199.90)
        assert result["previous_price"] == 299.90
        assert result["savings"] == 100.00
        assert result["discount_percent"] == 33.34

    def test__apply_rejects_invalid(self):
        """_apply nao modifica se old_price <= current_price."""
        product = {"loja": "Mercado Livre", "current_price": 300}
        result = PreviousPriceEnricher._apply(product, 200, 300)
        assert result is product
        assert "previous_price" not in result

    def test_reset_count(self):
        """reset_count zera o contador de enriquecimentos."""
        enricher = PreviousPriceEnricher(max_per_cycle=2)
        enricher._enrich_count = 5
        enricher.reset_count()
        assert enricher._enrich_count == 0

    def test_enrich_uses_preco_atual_key(self):
        """Suporta chave 'preco_atual' como alternativa a 'current_price'."""
        enricher = PreviousPriceEnricher()

        with patch.object(PreviousPriceEnricher, "_get_store") as mock_get_store:
            mock_store = MagicMock()
            mock_store.product_from_url.return_value = {"preco_antigo": "R$ 500,00"}
            mock_get_store.return_value = mock_store

            product = {
                "loja": "Mercado Livre",
                "preco_atual": 300,
                "product_url": "https://mercadolivre.com.br/MLB-789",
            }
            result = enricher.enrich(product)
            assert result["previous_price"] == 500.0
            assert result["savings"] == 200.0

    def test_enrich_detects_captcha_marker_as_error(self):
        """Paginas de bloqueio/captcha resultam em erro capturado."""
        enricher = PreviousPriceEnricher(max_per_cycle=5)

        with patch.object(PreviousPriceEnricher, "_get_store") as mock_get_store:
            mock_store = MagicMock()
            # product_from_url pode lancar MercadoLivreBlockedError
            from src.stores.mercado_livre import MercadoLivreBlockedError
            mock_store.product_from_url.side_effect = MercadoLivreBlockedError("captcha")
            mock_get_store.return_value = mock_store

            product = {
                "loja": "Mercado Livre",
                "current_price": 100,
                "product_url": "https://mercadolivre.com.br/MLB-block",
            }
            result = enricher.enrich(product)
            assert result is product
            assert "previous_price" not in result


class TestEnricherIntegration:
    """Testes de integracao com o fluxo do runner."""

    def test_enricher_integration_in_runner_deliver_pending(self):
        """Simula o fluxo do runner._deliver_pending."""
        enricher = PreviousPriceEnricher(max_per_cycle=3)

        with patch.object(PreviousPriceEnricher, "_get_store") as mock_get_store:
            mock_store = MagicMock()
            mock_store.product_from_url.return_value = {"preco_antigo": "R$ 249,00"}
            mock_get_store.return_value = mock_store

            # Simula items da fila (queue.pending())
            queue_items = [
                {
                    "id": 1,
                    "store": "Mercado Livre",
                    "current_price": 149.90,
                    "previous_price": 0.0,  # como vem do DB antes do enriquecimento
                    "product_url": "https://mercadolivre.com.br/MLB-001",
                    "title": "Produto A",
                    "image_url": "",
                },
                {
                    "id": 2,
                    "store": "Mercado Livre",
                    "current_price": 199.90,
                    "previous_price": 0.0,
                    "product_url": "https://mercadolivre.com.br/MLB-002",
                    "title": "Produto B",
                    "image_url": "",
                },
                {
                    "id": 3,
                    "store": "Amazon",
                    "current_price": 89.90,
                    "previous_price": 0.0,
                    "product_url": "https://amazon.com.br/dp/XYZ",
                    "title": "Produto C",
                    "image_url": "",
                },
                {
                    "id": 4,
                    "store": "Mercado Livre",
                    "current_price": 50.00,
                    "previous_price": 0.0,
                    "product_url": "https://mercadolivre.com.br/MLB-001",  # duplicado
                    "title": "Produto D",
                    "image_url": "",
                },
            ]

            for item in queue_items:
                if enricher._enrich_count >= enricher._max_per_cycle:
                    break
                enricher.enrich(item)

            # Produto A: enriquecido
            assert queue_items[0]["previous_price"] == 249.0
            assert queue_items[0]["savings"] == 99.10
            assert queue_items[0]["discount_percent"] == 39.80

            # Produto B: enriquecido
            assert queue_items[1]["previous_price"] == 249.0
            assert queue_items[1]["savings"] == 49.10

            # Produto C: Amazon, ignorado
            assert queue_items[2]["previous_price"] == 0.0

            # Produto D: duplicado (mesmo URL de A), usa cache
            assert queue_items[3]["previous_price"] == 249.0

            # Apenas 2 chamadas reais (A e B), C ignorado, D cache
            assert enricher._enrich_count == 2
            assert mock_store.product_from_url.call_count == 2

    @staticmethod
    def _sqlite_row(store="Mercado Livre", previous_price=0.0, product_url=None):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.execute(
            "CREATE TABLE queue_item (id INTEGER, store TEXT, current_price REAL, "
            "previous_price REAL, product_url TEXT, title TEXT, image_url TEXT)"
        )
        connection.execute(
            "INSERT INTO queue_item VALUES (1, ?, 100, ?, ?, 'Produto', 'imagem')",
            (store, previous_price, product_url),
        )
        row = connection.execute("SELECT * FROM queue_item").fetchone()
        connection.close()
        return row

    def test_real_sqlite_row_is_centrally_converted_and_reaches_delivery(self):
        from src.promotion_hunter.runner import PromotionHunterRunner

        row = self._sqlite_row(
            product_url="https://mercadolivre.com.br/MLB-ROW"
        )
        queue = MagicMock()
        queue.pending.return_value = (row,)
        repository = MagicMock()
        repository.sent_count_since.return_value = 0
        repository.last_sent_at.return_value = None
        repository.start_attempt.return_value = 7
        policy = MagicMock()
        policy.max_messages_per_run = 1
        policy.evaluate.return_value = MagicMock(allowed=True)
        delivery = MagicMock(destination="5511999999999")
        delivery.send.return_value = (True, "")
        enricher = PreviousPriceEnricher()

        with patch.object(enricher, "_get_store") as get_store:
            get_store.return_value.product_from_url.return_value = {
                "preco_antigo": "R$ 150,00"
            }
            runner = PromotionHunterRunner(
                MagicMock(), queue, repository, policy,
                delivery=delivery, enricher=enricher,
            )
            sent, blocked, errors = runner._deliver_pending()

        delivered = delivery.send.call_args.args[0]
        assert (sent, blocked, errors) == (1, 0, [])
        assert isinstance(delivered, dict)
        assert delivered["previous_price"] == 150.0
        assert delivered["title"] == "Produto"

    def test_sqlite_rows_for_other_stores_and_valid_previous_are_not_scraped(self):
        enricher = PreviousPriceEnricher()
        with patch.object(enricher, "_get_store") as get_store:
            for row in (
                self._sqlite_row("Amazon", product_url="https://amazon.invalid"),
                self._sqlite_row("Shopee", product_url="https://shopee.invalid"),
                self._sqlite_row("Mercado Livre", previous_price=150),
                self._sqlite_row("Mercado Livre", product_url=None),
            ):
                item = dict(row)
                assert enricher.enrich(item) is item
            get_store.assert_not_called()

    def test_enrichment_failure_does_not_interrupt_delivery(self):
        from src.promotion_hunter.runner import PromotionHunterRunner

        row = self._sqlite_row(product_url="https://mercadolivre.com.br/MLB-FAIL")
        queue = MagicMock()
        queue.pending.return_value = (row,)
        repository = MagicMock()
        repository.sent_count_since.return_value = 0
        repository.last_sent_at.return_value = None
        repository.start_attempt.return_value = 8
        policy = MagicMock()
        policy.evaluate.return_value = MagicMock(allowed=True)
        delivery = MagicMock(destination="5511999999999")
        delivery.send.return_value = (True, "")
        enricher = MagicMock()
        enricher.enrich.side_effect = RuntimeError("timeout controlado")
        runner = PromotionHunterRunner(
            MagicMock(), queue, repository, policy,
            delivery=delivery, enricher=enricher,
        )

        sent, blocked, errors = runner._deliver_pending()

        assert (sent, blocked) == (1, 0)
        assert errors == ["previous_price_enrichment: timeout controlado"]
        delivery.send.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
