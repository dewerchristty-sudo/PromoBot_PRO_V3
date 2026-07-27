from datetime import datetime, timedelta

from src.ui.daily_deals_page import DailyDealsPage


def test_discount_percent_uses_highest_collected_price():
    product = {"preco_valor": 80, "maior_preco": 100}
    assert DailyDealsPage.discount_percent(product) == 20


def test_discount_percent_rejects_price_without_real_drop():
    assert DailyDealsPage.discount_percent(
        {"preco_valor": 100, "maior_preco": 100}
    ) == 0


def test_recent_offer_expires_after_configured_window():
    now = datetime(2026, 7, 23, 12, 0, 0)
    recent = {"data": (now - timedelta(hours=2)).isoformat(sep=" ")}
    expired = {"data": (now - timedelta(hours=25)).isoformat(sep=" ")}

    assert DailyDealsPage.is_recent(recent, now, 24)
    assert not DailyDealsPage.is_recent(expired, now, 24)
