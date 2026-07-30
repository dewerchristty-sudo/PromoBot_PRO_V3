from src.promotion_hunter.contracts import PromotionSource
from src.promotion_hunter.registry import CollectorRegistry
from src.promotion_hunter.repository import PromotionHunterRepository
from src.promotion_hunter.service import PromotionHunterService
from tests.promotion_hunter.fakes import FakeCollector, FakePipeline


def build(tmp_path, registrations):
    repository = PromotionHunterRepository(tmp_path / "hunter.db")
    repository.migrate()
    registry = CollectorRegistry()
    for source_type, collector in registrations:
        registry.register("Mercado Livre", source_type, collector)
    pipeline = FakePipeline()
    return (
        PromotionHunterService(registry, pipeline, repository),
        pipeline,
        repository,
    )


def source(source_id, source_type, configuration=None):
    return PromotionSource(
        source_id, source_type, "Mercado Livre", source_id,
        configuration or {},
    )


def test_service_does_not_read_terms_directly(tmp_path):
    collector = FakeCollector([{"id": "1", "titulo": "Produto"}])
    service, pipeline, repository = build(
        tmp_path, [("custom_source", collector)]
    )
    result = service.run([source(
        "custom", "custom_source",
        {"configuration_without_terms": True},
    )])
    repository.close()
    assert result.status == "success"
    assert result.unique_count == 1
    assert len(pipeline.calls) == 1


def test_collector_failure_does_not_stop_other_sources(tmp_path):
    failed = FakeCollector(error=RuntimeError("falha controlada"))
    good = FakeCollector([{"id": "2", "titulo": "Produto"}])
    service, _, repository = build(
        tmp_path, [("failed", failed), ("good", good)]
    )
    result = service.run([
        source("failed", "failed"),
        source("good", "good"),
    ])
    repository.close()
    assert result.status == "partial_success"
    assert [item.status for item in result.source_runs] == ["error", "success"]
    assert result.unique_count == 1


def test_repeated_products_across_sources_are_deduplicated(tmp_path):
    first = FakeCollector([{"id": "MLB1", "titulo": "Produto"}])
    second = FakeCollector([{"product_id": "MLB1", "title": "Produto"}])
    service, pipeline, repository = build(
        tmp_path, [("keyword", first), ("official_category", second)]
    )
    result = service.run([
        source("keyword", "keyword"),
        source("category", "official_category"),
    ])
    repository.close()
    assert result.collected_count == 2
    assert result.unique_count == 1
    assert len(pipeline.calls[0]) == 1
    assert result.decisions[0].source_ids == ("keyword", "category")
