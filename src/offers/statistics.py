from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import json
from typing import Any, Mapping

from src.database.offer_pipeline_repository import OfferPipelineRepository
from src.offers.activation import OfferActivationFlags
from src.stores.active import ACTIVE_STORE_NAMES


@dataclass(frozen=True, slots=True)
class OfferDashboardFilter:
    store: str = ""
    category: str = ""
    minimum_score: float | None = None
    queue_status: str = ""
    date_from: datetime | None = None
    date_to: datetime | None = None
    product_query: str = ""


@dataclass(frozen=True, slots=True)
class OfferMetrics:
    total_analyzed: int = 0
    total_approved: int = 0
    total_discarded: int = 0
    total_duplicate: int = 0
    total_blocked: int = 0
    total_queued: int = 0
    total_selected_shadow: int = 0
    average_processing_ms: float = 0.0
    average_score: float = 0.0
    maximum_score: float = 0.0
    minimum_score: float = 0.0
    excellent_offers: int = 0
    good_offers: int = 0
    current_mode: str = "legado"
    active_scheduler: str = "legado"
    canary_percent: int = 0
    legacy_sends: int = 0
    intelligent_sends: int = 0
    comparisons: int = 0
    rollbacks: int = 0
    differences: int = 0


@dataclass(frozen=True, slots=True)
class OfferDashboardSnapshot:
    metrics: OfferMetrics
    queue_counts: Mapping[str, int]
    top_offers: tuple[Mapping[str, Any], ...]
    by_store: tuple[Mapping[str, Any], ...]
    by_category: tuple[Mapping[str, Any], ...]
    hourly: tuple[Mapping[str, Any], ...]
    recent_logs: tuple[Mapping[str, Any], ...]
    stores: tuple[str, ...]
    categories: tuple[str, ...]
    generated_at: datetime


class OfferStatistics:
    """Consultas prontas; nunca recalcula Score ou histórico."""

    QUEUE_STATES = (
        "queued", "reserved", "selected_shadow", "blocked", "expired",
        "discarded", "failed", "cancelled",
    )

    def __init__(self, repository: OfferPipelineRepository):
        self.repository = repository

    def snapshot(
        self,
        filters: OfferDashboardFilter | None = None,
        top_limit: int = 20,
        log_limit: int = 100,
    ) -> OfferDashboardSnapshot:
        filters = filters or OfferDashboardFilter()
        where, params = self.where_clause(filters)
        metrics = self.metrics(where, params)
        flags = OfferActivationFlags.from_environment()
        activation = self.repository.canary_metrics()
        metrics = replace(
            metrics,
            current_mode=flags.mode,
            active_scheduler=(
                "inteligente"
                if flags.intelligent_scheduler_enabled
                and flags.canary_percent > 0
                else "legado"
            ),
            canary_percent=flags.canary_percent,
            **activation,
        )
        return OfferDashboardSnapshot(
            metrics=metrics,
            queue_counts=self.queue_counts(where, params),
            top_offers=tuple(self.top_offers(
                where,
                params,
                min(max(int(top_limit), 1), 100),
            )),
            by_store=tuple(self.grouped("store", where, params)),
            by_category=tuple(self.grouped("category", where, params)),
            hourly=tuple(self.hourly(where, params)),
            recent_logs=tuple(self.recent_logs(
                where,
                params,
                min(max(int(log_limit), 1), 500),
            )),
            stores=tuple(ACTIVE_STORE_NAMES),
            categories=tuple(self.distinct_values("category")),
            generated_at=datetime.now(timezone.utc),
        )

    def metrics(self, where, params):
        row = self.repository.read_one(f"""
            SELECT
                COUNT(*) AS total_analyzed,
                COALESCE(SUM(i.filter_approved), 0) AS total_approved,
                COALESCE(SUM(CASE WHEN q.status='discarded' THEN 1 ELSE 0 END), 0)
                    AS total_discarded,
                COALESCE(SUM(CASE
                    WHEN i.duplicate_type NOT IN ('', 'novo_produto', 'nova_promocao')
                    THEN 1 ELSE 0 END), 0) AS total_duplicate,
                COALESCE(SUM(CASE WHEN q.status='blocked' THEN 1 ELSE 0 END), 0)
                    AS total_blocked,
                COUNT(DISTINCT q.id)
                    AS total_queued,
                COALESCE(SUM(CASE
                    WHEN i.scheduler_status='selected_shadow' THEN 1 ELSE 0 END), 0)
                    AS total_selected_shadow,
                COALESCE(AVG(i.processing_ms), 0) AS average_processing_ms,
                COALESCE(AVG(i.score), 0) AS average_score,
                COALESCE(MAX(i.score), 0) AS maximum_score,
                COALESCE(MIN(i.score), 0) AS minimum_score,
                COALESCE(SUM(CASE
                    WHEN i.classification IN (
                        'oferta_excepcional', 'oferta_excelente'
                    ) THEN 1 ELSE 0 END), 0)
                    AS excellent_offers,
                COALESCE(SUM(CASE
                    WHEN i.classification IN (
                        'oferta_muito_boa', 'oferta_boa', 'boa_oferta'
                    ) THEN 1 ELSE 0 END), 0)
                    AS good_offers
            FROM offer_pipeline_items i
            LEFT JOIN offer_queue q ON q.id=i.queue_item_id
            {where}
        """, params)
        if not row:
            return OfferMetrics()
        available = set(row.keys())
        return OfferMetrics(**{
            key: row[key]
            for key in OfferMetrics.__dataclass_fields__
            if key in available
        })

    def queue_counts(self, where, params):
        rows = self.repository.read_all(f"""
            SELECT q.status, COUNT(DISTINCT q.id) AS total
            FROM offer_pipeline_items i
            JOIN offer_queue q ON q.id=i.queue_item_id
            {where}
            GROUP BY q.status
        """, params)
        result = {state: 0 for state in self.QUEUE_STATES}
        result.update({row["status"]: row["total"] for row in rows})
        return result

    def top_offers(self, where, params, limit):
        return [
            self.row_dict(row)
            for row in self.repository.read_all(f"""
                WITH history AS (
                    SELECT canonical_identity,
                           MIN(price) AS historical_minimum,
                           MAX(price) AS historical_maximum,
                           AVG(price) AS historical_average,
                           COUNT(*) AS history_samples
                    FROM offer_price_observations
                    GROUP BY canonical_identity
                )
                SELECT i.id AS pipeline_item_id, i.title, i.store,
                       q.category, q.current_price, q.previous_price,
                       COALESCE(h.historical_minimum, 0) AS historical_minimum,
                       COALESCE(h.historical_maximum, 0) AS historical_maximum,
                       COALESCE(h.historical_average, 0) AS historical_average,
                       COALESCE(h.history_samples, 0) AS history_samples,
                       i.score, i.classification,
                       COALESCE(q.status, '') AS status,
                       COALESCE(q.blocked_reason, '') AS blocked_reason,
                       i.scheduler_status, i.duplicate_type,
                       i.diagnostic_json, i.created_at
                FROM offer_pipeline_items i
                LEFT JOIN offer_queue q ON q.id=i.queue_item_id
                LEFT JOIN history h
                    ON h.canonical_identity=i.canonical_identity
                {where}
                ORDER BY i.score DESC, i.created_at DESC, i.id DESC
                LIMIT ?
            """, [*params, limit])
        ]

    def grouped(self, field_name, where, params):
        if field_name not in {"store", "category"}:
            raise ValueError("Agrupamento inválido.")
        expression = (
            "COALESCE(NULLIF(TRIM(i.store), ''), 'Sem loja')"
            if field_name == "store"
            else "COALESCE(NULLIF(TRIM(q.category), ''), 'Sem categoria')"
        )
        return [
            self.row_dict(row)
            for row in self.repository.read_all(f"""
                SELECT {expression} AS label,
                       COUNT(*) AS total,
                       ROUND(AVG(i.score), 2) AS average_score,
                       SUM(i.filter_approved) AS approved,
                       SUM(CASE WHEN q.status='blocked' THEN 1 ELSE 0 END)
                           AS blocked
                FROM offer_pipeline_items i
                LEFT JOIN offer_queue q ON q.id=i.queue_item_id
                {where}
                GROUP BY {expression}
                ORDER BY total DESC, label
                LIMIT 30
            """, params)
        ]

    def hourly(self, where, params):
        return [
            self.row_dict(row)
            for row in self.repository.read_all(f"""
                SELECT substr(i.created_at, 1, 13) || ':00' AS label,
                       COUNT(*) AS total,
                       ROUND(AVG(i.score), 2) AS average_score,
                       ROUND(AVG(i.processing_ms), 3) AS average_processing_ms
                FROM offer_pipeline_items i
                LEFT JOIN offer_queue q ON q.id=i.queue_item_id
                {where}
                GROUP BY substr(i.created_at, 1, 13)
                ORDER BY label DESC
                LIMIT 24
            """, params)
        ][::-1]

    def recent_logs(self, where, params, limit):
        return [
            self.row_dict(row)
            for row in self.repository.read_all(f"""
                SELECT i.id, i.created_at, i.title, i.store, i.score,
                       i.classification, i.queue_status, i.scheduler_status,
                       i.duplicate_type, i.error, i.processing_ms,
                       i.diagnostic_json
                FROM offer_pipeline_items i
                LEFT JOIN offer_queue q ON q.id=i.queue_item_id
                {where}
                ORDER BY i.created_at DESC, i.id DESC
                LIMIT ?
            """, [*params, limit])
        ]

    def inspect(self, pipeline_item_id):
        rows = self.top_offers(
            "WHERE i.id=?",
            [int(pipeline_item_id)],
            1,
        )
        if not rows:
            return None
        item = rows[0]
        raw = item.get("diagnostic_json") or "{}"
        item["diagnostic"] = json.loads(raw)
        queue_id_row = self.repository.read_one(
            "SELECT queue_item_id FROM offer_pipeline_items WHERE id=?",
            (int(pipeline_item_id),),
        )
        queue_id = queue_id_row["queue_item_id"] if queue_id_row else None
        item["decisions"] = [
            self.row_dict(row)
            for row in (
                self.repository.decisions(queue_id) if queue_id else ()
            )
        ]
        return item

    def distinct_values(self, field_name):
        if field_name == "store":
            expression = "TRIM(store)"
            table = "offer_pipeline_items"
        elif field_name == "category":
            expression = "TRIM(category)"
            table = "offer_queue"
        else:
            raise ValueError("Campo inválido.")
        rows = self.repository.read_all(f"""
            SELECT DISTINCT {expression} AS value FROM {table}
            WHERE {expression} <> '' ORDER BY value
        """)
        return [row["value"] for row in rows]

    @staticmethod
    def where_clause(filters):
        clauses = [
            "lower(i.store) IN (lower(?), lower(?), lower(?))"
        ]
        params = list(ACTIVE_STORE_NAMES)
        if filters.store:
            clauses.append("lower(i.store)=lower(?)")
            params.append(filters.store)
        if filters.category:
            clauses.append("lower(q.category)=lower(?)")
            params.append(filters.category)
        if filters.minimum_score is not None:
            clauses.append("i.score >= ?")
            params.append(float(filters.minimum_score))
        if filters.queue_status:
            clauses.append("q.status=?")
            params.append(filters.queue_status)
        if filters.date_from:
            clauses.append("i.created_at >= ?")
            params.append(OfferStatistics.iso(filters.date_from))
        if filters.date_to:
            clauses.append("i.created_at <= ?")
            params.append(OfferStatistics.iso(filters.date_to))
        if filters.product_query:
            clauses.append("lower(i.title) LIKE lower(?)")
            params.append(f"%{filters.product_query.strip()}%")
        return (
            ("WHERE " + " AND ".join(clauses)) if clauses else "",
            params,
        )

    @staticmethod
    def row_dict(row):
        return {key: row[key] for key in row.keys()}

    @staticmethod
    def iso(value):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
