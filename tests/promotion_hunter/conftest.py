import pytest


@pytest.fixture(autouse=True)
def authorized_unit_transport(monkeypatch):
    """Testes de transporte usam autorizacao; testes da trava sobrescrevem."""
    monkeypatch.setenv("PROMOTION_HUNTER_REAL_SEND_AUTHORIZED", "true")
    monkeypatch.setenv("PROMOTION_HUNTER_LIVE_DELIVERY", "true")
