import pytest

from src.promotion_hunter.contracts import CollectionResult, PromotionSource


def test_source_requires_generic_identity_fields():
    with pytest.raises(ValueError, match="source_id"):
        PromotionSource("", "keyword", "Mercado Livre", "Teste")


def test_collection_result_reports_exact_returned_count():
    source = PromotionSource("a", "keyword", "Mercado Livre", "A")
    result = CollectionResult(source, ({"id": "1"}, {"id": "2"}))
    assert result.returned_count == 2
