from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.promotion_hunter.delivery.authorization import (
    RealDeliveryNotAuthorized,
    real_delivery_authorized,
    require_real_delivery_authorized,
)
from src.promotion_hunter.delivery.notifier_adapter import (
    PromotionHunterDeliveryAdapter,
)
from scripts import run_promotion_hunter_pilot as pilot


@pytest.mark.parametrize("live,authorized,expected", [
    (None, None, False),
    ("true", None, False),
    (None, "true", False),
    ("false", "true", False),
    ("true", "false", False),
    ("true", "true", True),
])
def test_double_gate_requires_both(monkeypatch, live, authorized, expected):
    for name, value in (
        ("PROMOTION_HUNTER_LIVE_DELIVERY", live),
        ("PROMOTION_HUNTER_REAL_SEND_AUTHORIZED", authorized),
    ):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    assert real_delivery_authorized() is expected
    if expected:
        require_real_delivery_authorized(boundary="test")
    else:
        with pytest.raises(RealDeliveryNotAuthorized):
            require_real_delivery_authorized(boundary="test")


def test_adapter_rechecks_before_notifier(monkeypatch):
    monkeypatch.setenv("PROMOTION_HUNTER_LIVE_DELIVERY", "true")
    monkeypatch.setenv("PROMOTION_HUNTER_REAL_SEND_AUTHORIZED", "false")
    notifier = MagicMock()
    notifier.whatsapp_category_groups.return_value = {
        "smartphones_tecnologia": "123456789012345678@g.us"
    }
    notifier.whatsapp_category.return_value = "smartphones_tecnologia"
    adapter = PromotionHunterDeliveryAdapter(notifier, "")
    result = adapter.send({
        "store": "Amazon", "title": "Smartphone", "current_price": 10,
        "previous_price": 20, "image_url": "https://image.test/a.jpg",
        "product_url": "https://amazon.com.br/dp/B000000001",
        "category": "smartphones_tecnologia", "search_term": "",
        "breadcrumb": "", "original_category": "",
    })
    assert not result.success
    notifier.send_whatsapp_message.assert_not_called()


def test_pilot_refuses_live_before_opening_database(monkeypatch):
    monkeypatch.setenv("PROMOTION_HUNTER_LIVE_DELIVERY", "true")
    monkeypatch.setenv("PROMOTION_HUNTER_REAL_SEND_AUTHORIZED", "false")
    with pytest.raises(RealDeliveryNotAuthorized):
        pilot.build_runtime(SimpleNamespace(mode="live"))
