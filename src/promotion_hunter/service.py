from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Iterable
from uuid import uuid4

from .contracts import PromotionSource
from .decision_mapper import DecisionMapper
from .models import HunterRunResult, NormalizedProduct, SourceRunResult
from .normalization import ProductNormalizer
from .registry import CollectorRegistry
from .repository import PromotionHunterRepository


logger = logging.getLogger(__name__)


class PromotionHunterService:
    def __init__(
        self,
        registry: CollectorRegistry,
        pipeline: Any,
        repository: PromotionHunterRepository,
        normalizer: ProductNormalizer | None = None,
        decision_mapper: DecisionMapper | None = None,
    ) -> None:
        self.registry = registry
        self.pipeline = pipeline
        self.repository = repository
        self.normalizer = normalizer or ProductNormalizer()
        self.decision_mapper = decision_mapper or DecisionMapper()

    @staticmethod
    def _sanitize_error(exc: Exception) -> str:
        message = " ".join(str(exc).split())
        return message[:300]

    def run(self, sources: Iterable[PromotionSource]) -> HunterRunResult:
        run_id = uuid4().hex
        started_at = datetime.now(timezone.utc)
        self.repository.start_run(run_id, started_at.isoformat())
        try:
            return self._run_started(sources, run_id, started_at)
        except Exception:
            try:
                self.repository.finish_run(
                    run_id,
                    "failed",
                    0,
                    0,
                    datetime.now(timezone.utc).isoformat(),
                )
            except Exception:
                logger.exception("Falha ao finalizar run interrompida do Hunter")
            raise

    def _run_started(
        self,
        sources: Iterable[PromotionSource],
        run_id: str,
        started_at: datetime,
    ) -> HunterRunResult:
        source_runs: list[SourceRunResult] = []
        unique: dict[str, NormalizedProduct] = {}
        collected_count = 0

        for source in sources:
            if not source.enabled:
                continue
            self.repository.upsert_source(source)
            source_started = datetime.now(timezone.utc)
            try:
                collector = self.registry.resolve(source)
                collection = collector.collect(source)
                products = collection.products
                if source.limit is not None:
                    products = products[:source.limit]
                collected_count += len(products)
                normalized: list[NormalizedProduct] = []
                for product in products:
                    normalized.append(
                        self.normalizer.normalize(
                            product,
                            source,
                            collection.finished_at,
                        )
                    )
                before = len(unique)
                for product in normalized:
                    existing = unique.get(product.deduplication_key)
                    unique[product.deduplication_key] = (
                        existing.merge_provenance(product)
                        if existing else product
                    )
                added = len(unique) - before
                source_result = SourceRunResult(
                    source_id=source.source_id,
                    status=collection.status,
                    returned_count=collection.returned_count,
                    normalized_count=len(normalized),
                    added_count=added,
                    error_type=collection.error_type,
                    error_message=collection.error_message,
                )
                source_finished = collection.finished_at
            except Exception as exc:
                source_finished = datetime.now(timezone.utc)
                source_result = SourceRunResult(
                    source_id=source.source_id,
                    status="error",
                    returned_count=0,
                    normalized_count=0,
                    added_count=0,
                    error_type=type(exc).__name__,
                    error_message=self._sanitize_error(exc),
                )

            source_runs.append(source_result)
            self.repository.record_source_run(
                run_id=run_id,
                source_id=source_result.source_id,
                status=source_result.status,
                returned_count=source_result.returned_count,
                normalized_count=source_result.normalized_count,
                added_count=source_result.added_count,
                error_type=source_result.error_type,
                error_message=source_result.error_message,
                started_at=source_started.isoformat(),
                finished_at=source_finished.isoformat(),
            )

        products = tuple(unique.values())
        decisions = ()
        if products:
            batch = self.pipeline.process_batch([
                product.pipeline_payload() for product in products
            ])
            items = tuple(getattr(batch, "items", batch))
            if len(items) != len(products):
                raise ValueError(
                    "Pipeline retornou quantidade incompatível de resultados"
                )
            decisions = tuple(
                self.decision_mapper.map(product, item)
                for product, item in zip(products, items)
            )
            self.repository.record_decisions(run_id, decisions)

        errors = sum(item.status == "error" for item in source_runs)
        if source_runs and errors == len(source_runs):
            status = "failed"
        elif errors:
            status = "partial_success"
        elif not products:
            status = "zero_results"
        else:
            status = "success"
        finished_at = datetime.now(timezone.utc)
        self.repository.finish_run(
            run_id,
            status,
            collected_count,
            len(products),
            finished_at.isoformat(),
        )
        return HunterRunResult(
            run_id=run_id,
            status=status,
            source_runs=tuple(source_runs),
            collected_count=collected_count,
            unique_count=len(products),
            decisions=decisions,
            normalized_products=products,
            started_at=started_at,
            finished_at=finished_at,
        )
