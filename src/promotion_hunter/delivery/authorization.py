"""Trava universal de autorizacao para entregas reais do Hunter."""
from __future__ import annotations

import os


TRUE_VALUES = frozenset({"1", "true", "yes", "on", "sim"})


class RealDeliveryNotAuthorized(PermissionError):
    """A entrega foi recusada antes de qualquer chamada ao transporte."""


def env_true(name: str) -> bool:
    return os.getenv(name, "false").strip().casefold() in TRUE_VALUES


def real_delivery_authorized() -> bool:
    return (
        env_true("PROMOTION_HUNTER_LIVE_DELIVERY")
        and env_true("PROMOTION_HUNTER_REAL_SEND_AUTHORIZED")
    )


def require_real_delivery_authorized(*, boundary: str = "delivery") -> None:
    if real_delivery_authorized():
        return
    raise RealDeliveryNotAuthorized(
        "Entrega real bloqueada em " + boundary + ": sao obrigatorios "
        "PROMOTION_HUNTER_LIVE_DELIVERY=true e "
        "PROMOTION_HUNTER_REAL_SEND_AUTHORIZED=true."
    )
