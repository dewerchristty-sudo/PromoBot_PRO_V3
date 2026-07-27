from datetime import datetime, time, timedelta, timezone
import unittest
from unittest.mock import patch

from src.collector_scheduler.config import (
    PriceCollectionSchedulerConfig, parse_times,
)
from src.collector_scheduler.manager import PriceCollectionScheduleManager
from src.collector_scheduler.models import SchedulerValidation
from src.collector_scheduler.runner import PriceCollectionSchedulerRunner


class FakeRepository:

    def __init__(self, rows=None, fail=False):
        self.rows = rows or [{
            "product_key": "MLB50957106", "store": "Mercado Livre",
        }]
        self.fail = fail
        self.closed = False

    def migrate(self):
        if self.fail:
            raise OSError("banco indisponivel")

    def read_all(self, _sql, _params):
        if self.fail:
            raise OSError("banco indisponivel")
        return self.rows

    def close(self):
        self.closed = True


class CollectorSchedulerTest(unittest.TestCase):

    def config(self, **changes):
        values = {
            "enabled": True,
            "times": (time(9), time(15), time(21)),
            "allowed_stores": ("mercado_livre",),
            "max_products_per_run": 100,
            "retry_on_failure": True,
            "retry_minutes": 15,
            "log_level": "INFO",
        }
        values.update(changes)
        return PriceCollectionSchedulerConfig(**values)

    @staticmethod
    def ready():
        return SchedulerValidation(True, "READY")

    def runner(self, collector, **kwargs):
        return PriceCollectionSchedulerRunner(
            kwargs.pop("config", self.config()),
            collector=collector,
            repository_factory=kwargs.pop(
                "repository_factory", lambda: FakeRepository()
            ),
            preflight=kwargs.pop("preflight", self.ready),
            **kwargs,
        )

    def test_horarios_e_proximo_horario(self):
        self.assertEqual(
            parse_times("21:00,09:00,15:00"),
            (time(9), time(15), time(21)),
        )
        manager = PriceCollectionScheduleManager(self.config())
        now = datetime(2026, 7, 26, 10, tzinfo=timezone.utc)
        self.assertEqual(manager.next_run(now).hour, 15)
        late = datetime(2026, 7, 26, 22, tzinfo=timezone.utc)
        self.assertEqual(manager.next_run(late).date(), late.date() + timedelta(days=1))

    @patch("src.collector_scheduler.runner.write_run")
    def test_execucao_unica(self, _write):
        runner = self.runner(lambda _store, _key: ([
            {"stored": True, "status": "STORED", "reason": ""}
        ], None))
        result = runner.run_once()
        self.assertEqual(result.products, 1)
        self.assertEqual(result.valid_observations, 1)

    @patch("src.collector_scheduler.runner.write_status")
    @patch("src.collector_scheduler.runner.write_run")
    def test_multiplos_horarios_com_limite_finito(self, _run, _status):
        now = [datetime(2026, 7, 26, 8, 59, tzinfo=timezone.utc)]

        def sleep(seconds):
            now[0] += timedelta(seconds=seconds)

        runner = self.runner(
            lambda _store, _key: ([], None),
            clock=lambda: now[0], sleeper=sleep,
            config=self.config(times=(time(9), time(9, 1))),
        )
        results = runner.run_scheduled(max_cycles=2)
        self.assertEqual(len(results), 2)

    @patch("src.collector_scheduler.runner.write_run")
    def test_retry_uma_unica_vez(self, _write):
        calls = []
        sleeps = []

        def collector(_store, _key):
            calls.append(1)
            if len(calls) == 1:
                raise TimeoutError("timeout")
            return ([{"stored": True, "status": "STORED", "reason": ""}], None)

        result = self.runner(
            collector, sleeper=sleeps.append
        ).run_once()
        self.assertEqual(len(calls), 2)
        self.assertEqual(result.retries, 1)
        self.assertEqual(sleeps, [900])

    @patch("src.collector_scheduler.runner.write_run")
    def test_timeout_sem_retry(self, _write):
        runner = self.runner(
            lambda _store, _key: (_ for _ in ()).throw(
                TimeoutError("timeout")
            ),
            config=self.config(retry_on_failure=False),
        )
        result = runner.run_once()
        self.assertEqual(result.failures, 1)
        self.assertEqual(result.retries, 0)
        self.assertIn("TIMEOUT", result.details[0]["reason"])

    @patch("src.collector_scheduler.runner.write_run")
    def test_perda_de_sessao(self, _write):
        preflight = lambda: SchedulerValidation(
            False, "PREFLIGHT_FAILED", ("VERIFICATION_REQUIRED",)
        )
        result = self.runner(
            lambda *_args: ([], None), preflight=preflight
        ).run_once()
        self.assertEqual(result.status, "PREFLIGHT_FAILED")
        self.assertIn("VERIFICATION_REQUIRED", result.errors)

    @patch("src.collector_scheduler.runner.write_run")
    def test_deduplicacao_e_reportada(self, _write):
        result = self.runner(lambda _store, _key: ([
            {
                "stored": False, "status": "REJECTED",
                "reason": "DUPLICATE_WITHIN_WINDOW",
            }
        ], None)).run_once()
        self.assertEqual(result.duplicates, 1)
        self.assertEqual(result.valid_observations, 0)

    @patch("src.collector_scheduler.runner.write_run")
    def test_banco_indisponivel(self, _write):
        runner = self.runner(
            lambda *_args: ([], None),
            repository_factory=lambda: FakeRepository(fail=True),
        )
        result = runner.run_once()
        self.assertEqual(result.status, "PREFLIGHT_FAILED")
        self.assertIn("DATABASE_UNAVAILABLE", result.errors[0])

    @patch("src.collector_scheduler.runner.write_run")
    def test_navegador_indisponivel(self, _write):
        preflight = lambda: SchedulerValidation(
            False, "PREFLIGHT_FAILED", ("BROWSER_UNAVAILABLE",)
        )
        result = self.runner(
            lambda *_args: ([], None), preflight=preflight
        ).run_once()
        self.assertIn("BROWSER_UNAVAILABLE", result.errors)

    @patch("src.collector_scheduler.runner.write_status")
    def test_desabilitado_nao_coleta(self, _status):
        called = []
        runner = self.runner(
            lambda *_args: called.append(True),
            config=self.config(enabled=False),
        )
        self.assertEqual(runner.run_scheduled(), [])
        self.assertEqual(called, [])

    def test_modulo_nao_importa_transportes(self):
        from pathlib import Path
        source = "\n".join(
            path.read_text(encoding="utf-8").casefold()
            for path in Path("src/collector_scheduler").glob("*.py")
        )
        for forbidden in (
            "src.core.notifier", "send_whatsapp", "evolution",
            "offercanary", "offerscheduler",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
