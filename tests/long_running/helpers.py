from datetime import datetime, timedelta
from pathlib import Path
import tempfile
from zoneinfo import ZoneInfo

from src.database.offer_pipeline_repository import OfferPipelineRepository
from src.price_history import (
    PriceHistoryConfig, RealPriceHistoryService, RealPriceObservation,
)

from .fixtures import TEST_IDENTITY, TEST_PRODUCT_KEY, TEST_URL


SAO_PAULO = ZoneInfo("America/Sao_Paulo")


class ControlledClock:

    def __init__(self, value=None):
        self.value = value or datetime(2026, 1, 5, 9, tzinfo=SAO_PAULO)

    def now(self):
        return self.value

    def advance(self, *, minutes=0, hours=0, days=0, seconds=0):
        self.value += timedelta(
            days=days, hours=hours, minutes=minutes, seconds=seconds
        )
        return self.value

    def sleep(self, seconds):
        self.advance(seconds=seconds)


class IsolatedHistory:

    def __init__(self, clock=None, config=None):
        self.temporary = tempfile.TemporaryDirectory(
            prefix="promobot_long_running_test_"
        )
        self.root = Path(self.temporary.name).resolve()
        self.database_path = self.root / "SIMULATED_TEST_DATA.db"
        self.clock = clock or ControlledClock()
        self.repository = OfferPipelineRepository(self.database_path)
        self.repository.migrate()
        self.service = RealPriceHistoryService(
            self.repository, config or PriceHistoryConfig()
        )

    def close(self):
        self.repository.close()
        self.temporary.cleanup()

    def observation(self, price, *, at=None, run_id=None, **changes):
        at = at or self.clock.now()
        values = {
            "product_key": TEST_PRODUCT_KEY,
            "store": "Mercado Livre",
            "canonical_identity": TEST_IDENTITY,
            "canonical_product_id": TEST_PRODUCT_KEY,
            "canonical_url": TEST_URL,
            "title": "SIMULATED TEST SSD",
            "price": price,
            "currency": "BRL",
            "observed_at": at,
            "source": "mercado_livre_persistent_browser",
            "run_id": run_id or f"simulated-{at.isoformat()}",
            "original_url": TEST_URL,
        }
        values.update(changes)
        return RealPriceObservation(**values)

    def record(self, price, **kwargs):
        return self.service.record(self.observation(price, **kwargs))

    def restart(self):
        self.repository.close()
        self.repository = OfferPipelineRepository(self.database_path)
        self.repository.migrate()
        self.service = RealPriceHistoryService(
            self.repository, self.service.config
        )

    def assert_isolated(self):
        assert self.database_path.is_relative_to(self.root)
        assert "promobot_long_running_test_" in str(self.root)
        assert self.database_path.name == "SIMULATED_TEST_DATA.db"


def valid_count(system):
    return len(system.repository.real_price_history(TEST_PRODUCT_KEY))


def rejection_count(system):
    return len(system.repository.price_history_rejections(TEST_PRODUCT_KEY))
