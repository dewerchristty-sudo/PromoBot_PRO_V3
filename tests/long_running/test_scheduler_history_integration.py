from datetime import time
import unittest
from unittest.mock import patch

from src.collector_scheduler.config import PriceCollectionSchedulerConfig
from src.collector_scheduler.models import SchedulerValidation
from src.collector_scheduler.runner import PriceCollectionSchedulerRunner
from src.offer_intelligence import OfferIntelligenceAnalyzer

from .fixtures import TEST_PRODUCT_KEY
from .helpers import IsolatedHistory, valid_count


class SchedulerHistoryIntegrationTest(unittest.TestCase):

    def setUp(self):
        self.system = IsolatedHistory()
        self.system.record("1000")

    def tearDown(self):
        self.system.close()

    def config(self, **changes):
        values = dict(
            enabled=True, times=(time(9), time(15), time(21)),
            allowed_stores=("mercado_livre",), max_products_per_run=1,
            retry_on_failure=True, retry_minutes=15, log_level="INFO",
        )
        values.update(changes)
        return PriceCollectionSchedulerConfig(**values)

    def runner(self, collector, **changes):
        config = changes.pop("config", self.config())
        return PriceCollectionSchedulerRunner(
            config, collector=collector, clock=self.system.clock.now,
            sleeper=self.system.clock.sleep,
            repository_factory=lambda: OfferPipelineRepositoryProxy(
                self.system.repository
            ),
            preflight=lambda: SchedulerValidation(True, "READY"),
        )

    @patch("src.collector_scheduler.runner.write_run")
    @patch("src.collector_scheduler.runner.write_status")
    def test_scheduler_tres_horarios_sem_sleep_real(self, _status, _run):
        calls = []

        def collector(_store, _key):
            calls.append(self.system.clock.now())
            result = self.system.record(
                str(1000 - len(calls) * 5),
                run_id=f"scheduler-{len(calls)}",
            )
            return ([{
                "stored": result.stored, "status": result.status,
                "reason": result.reason, "product_key": TEST_PRODUCT_KEY,
            }], self.system.service.analyze(TEST_PRODUCT_KEY))

        results = self.runner(collector).run_scheduled(max_cycles=3)
        self.assertEqual(len(results), 3)
        self.assertEqual([value.hour for value in calls], [15, 21, 9])
        self.assertEqual(valid_count(self.system), 4)

    @patch("src.collector_scheduler.runner.write_run")
    def test_retry_limitado_e_recuperacao(self, _run):
        attempts = []

        def collector(_store, _key):
            attempts.append(1)
            if len(attempts) == 1:
                raise TimeoutError("SIMULATED_TEST_DATA")
            result = self.system.record(
                "990", at=self.system.clock.now(),
                run_id="retry-success",
            )
            return ([{
                "stored": result.stored, "status": result.status,
                "reason": result.reason,
            }], None)

        self.system.clock.advance(hours=2)
        result = self.runner(collector).run_once()
        self.assertEqual(len(attempts), 2)
        self.assertEqual(result.retries, 1)
        self.assertEqual(valid_count(self.system), 2)

    @patch("src.collector_scheduler.runner.write_status")
    def test_scheduler_desabilitado_nao_executa(self, _status):
        calls = []
        result = self.runner(
            lambda *_: calls.append(1),
            config=self.config(enabled=False),
        ).run_scheduled()
        self.assertEqual(result, [])
        self.assertEqual(calls, [])


class OfferPipelineRepositoryProxy:
    """Impede que o runner feche o repositório compartilhado do teste."""

    def __init__(self, repository):
        self.repository = repository

    def migrate(self):
        self.repository.migrate()

    def read_all(self, sql, params):
        return self.repository.read_all(sql, params)

    def close(self):
        pass
