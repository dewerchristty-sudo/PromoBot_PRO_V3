from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from src.promotion_hunter.contracts import CollectionResult


class FakeCollector:
    def __init__(self, products=(), error: Exception | None = None):
        self.products = tuple(products)
        self.error = error
        self.sources = []

    def collect(self, source):
        self.sources.append(source)
        if self.error:
            raise self.error
        return CollectionResult(source=source, products=self.products)


@dataclass
class FakePipelineItem:
    run_id: str
    diagnostic: object
    analysis: object | None = None
    error: str = ""


class FakePipeline:
    def __init__(self, item_factory=None):
        self.calls = []
        self.item_factory = item_factory or approved_item

    def process_batch(self, products):
        self.calls.append(products)
        return SimpleNamespace(items=tuple(
            self.item_factory(product) for product in products
        ))


def approved_item(product):
    return FakePipelineItem(
        run_id="pipeline-run",
        diagnostic=SimpleNamespace(
            score=88.0,
            classification="excelente",
            filter_approved=True,
            duplicate=False,
            operational_blocks=(),
            queue_status="queued",
            reason="oferta_aprovada",
        ),
    )
