from datetime import datetime
import os
from pathlib import Path
import time
from zoneinfo import ZoneInfo

from src.database.offer_pipeline_repository import OfferPipelineRepository

from .manager import PriceCollectionScheduleManager
from .models import CollectionRunResult
from .reports import write_run, write_status
from .validation import operational_preflight, validate_config


class PriceCollectionSchedulerRunner:

    def __init__(
        self, config, collector=None, clock=None, sleeper=None,
        repository_factory=None, preflight=None,
    ):
        self.config = config
        self.collector = collector or self.default_collector
        self.clock = clock or (
            lambda: datetime.now(ZoneInfo("America/Sao_Paulo"))
        )
        self.sleeper = sleeper or time.sleep
        self.database_path = Path(os.getenv(
            "OFFER_SHADOW_DB_PATH", "offer_shadow.db"
        ))
        self.repository_factory = repository_factory or (
            lambda: OfferPipelineRepository(self.database_path)
        )
        self.preflight = preflight or (
            lambda: operational_preflight(self.database_path)
        )
        self.schedule = PriceCollectionScheduleManager(config)

    @staticmethod
    def default_collector(store, product_key):
        from scripts.collect_price_history import collect
        return collect(store, product_key, dry_run=False)

    def monitored_products(self):
        repository = self.repository_factory()
        try:
            repository.migrate()
            rows = repository.read_all("""
                SELECT product_key, store
                FROM offer_price_history
                WHERE valid=1 AND product_key<>''
                GROUP BY product_key, store
                ORDER BY MAX(observed_at) DESC
                LIMIT ?
            """, (self.config.max_products_per_run,))
            return [
                ("mercado_livre", row["product_key"])
                for row in rows
                if row["store"] == "Mercado Livre"
                and "mercado_livre" in self.config.allowed_stores
            ]
        finally:
            repository.close()

    def run_once(self):
        started = self.clock()
        config_status = validate_config(self.config)
        preflight = self.preflight()
        if not config_status.valid or not preflight.valid:
            errors = config_status.reasons + preflight.reasons
            result = self.result(
                "PREFLIGHT_FAILED", started, [], 0, errors
            )
            write_run(result)
            return result
        try:
            products = self.monitored_products()
        except Exception as error:
            result = self.result(
                "PREFLIGHT_FAILED", started, [], 0,
                (f"DATABASE_UNAVAILABLE: {error}",),
            )
            write_run(result)
            return result
        details = []
        failed = []
        for store, product_key in products:
            rows = self.execute_product(store, product_key)
            details.extend(rows)
            if any(row.get("status") == "COLLECTION_FAILED" for row in rows):
                failed.append((store, product_key))
        retries = 0
        if failed and self.config.retry_on_failure:
            retries = 1
            self.sleeper(self.config.retry_minutes * 60)
            for store, product_key in failed:
                details.extend(self.execute_product(store, product_key))
        result = self.result(
            "COMPLETED" if not failed else "COMPLETED_WITH_FAILURES",
            started, details, retries, (),
            product_count=len(products),
        )
        write_run(result)
        return result

    def execute_product(self, store, product_key):
        try:
            results, _analysis = self.collector(store, product_key)
            return list(results)
        except TimeoutError as error:
            return [{
                "product_key": product_key,
                "status": "COLLECTION_FAILED",
                "reason": f"TIMEOUT: {error}",
                "stored": False,
            }]
        except Exception as error:
            return [{
                "product_key": product_key,
                "status": "COLLECTION_FAILED",
                "reason": f"{type(error).__name__}: {error}",
                "stored": False,
            }]

    def run_scheduled(self, max_cycles=None):
        if not self.config.enabled:
            write_status({
                "status": "DISABLED", "next_run": None,
                "message": "Defina PRICE_COLLECTION_ENABLED=True.",
            })
            return []
        validation = validate_config(self.config)
        if not validation.valid:
            write_status({
                "status": validation.status,
                "reasons": validation.reasons, "next_run": None,
            })
            return []
        limit = max_cycles or self.schedule.finite_cycle_limit()
        results = []
        for _index in range(limit):
            next_run = self.schedule.next_run(self.clock())
            write_status({
                "status": "WAITING", "next_run": next_run,
                "remaining_cycles": limit - len(results),
            })
            self.wait_until(next_run)
            results.append(self.run_once())
        write_status({
            "status": "FINISHED", "next_run": None,
            "executed_cycles": len(results),
        })
        return results

    def wait_until(self, target):
        while True:
            seconds = (target - self.clock()).total_seconds()
            if seconds <= 0:
                return
            self.sleeper(min(seconds, 60))

    def result(
        self, status, started, details, retries, errors,
        product_count=0,
    ):
        ended = self.clock()
        return CollectionRunResult(
            status=status, started_at=started, ended_at=ended,
            next_run=self.schedule.next_run(ended),
            products=product_count,
            valid_observations=sum(
                bool(row.get("stored")) for row in details
            ),
            duplicates=sum(
                row.get("reason") == "DUPLICATE_WITHIN_WINDOW"
                for row in details
            ),
            failures=sum(
                row.get("status") == "COLLECTION_FAILED"
                for row in details
            ),
            retries=retries,
            duration_seconds=round(
                max((ended - started).total_seconds(), 0), 3
            ),
            errors=tuple(errors),
            details=tuple(details),
        )
