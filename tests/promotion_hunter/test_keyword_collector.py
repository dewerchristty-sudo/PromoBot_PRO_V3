from src.promotion_hunter.collectors import KeywordCollector
from src.promotion_hunter.contracts import PromotionSource


def test_keyword_collector_uses_injected_dependency_only():
    calls = []
    collector = KeywordCollector(
        lambda term, source: calls.append((term, source.source_id))
        or [{"id": term}]
    )
    source = PromotionSource(
        "kw", "keyword", "Mercado Livre", "Busca",
        {"terms": ["air fryer", "aspirador"]},
    )
    result = collector.collect(source)
    assert calls == [("air fryer", "kw"), ("aspirador", "kw")]
    assert result.returned_count == 2
