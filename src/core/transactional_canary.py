from dataclasses import dataclass
import logging
import os
import re

from src.core.delivery_models import normalize_delivery_destination


logger = logging.getLogger(__name__)

_TRUE_VALUES = frozenset({"1", "true", "yes", "on", "sim"})
_PHONE_PATTERN = re.compile(r"^\d{12,13}$")
_GROUP_PATTERN = re.compile(r"^\d{10,22}@g\.us$", re.IGNORECASE)
_TELEGRAM_PATTERN = re.compile(r"^-?\d{5,22}$")


def normalize_canary_destination(destination):
    value = str(destination or "").strip()
    if not value:
        return None
    group_value = re.sub(r"\s", "", value)
    if _GROUP_PATTERN.fullmatch(group_value):
        return group_value.casefold()
    compact = re.sub(r"[\s()+.-]", "", value)
    telegram_value = re.sub(r"\s", "", value)
    if (
        _PHONE_PATTERN.fullmatch(compact)
        or _TELEGRAM_PATTERN.fullmatch(telegram_value)
    ):
        return normalize_delivery_destination(compact)
    return None


def mask_canary_value(value):
    digits = re.sub(r"\D", "", str(value or ""))
    return f"***{digits[-4:]}" if digits else "***valor"


@dataclass(frozen=True, slots=True)
class TransactionalCanaryConfig:
    enabled: bool = False
    destinations: frozenset[str] = frozenset()

    @classmethod
    def from_environment(cls, environ=None, diagnostic_logger=None):
        environ = os.environ if environ is None else environ
        diagnostic_logger = diagnostic_logger or logger
        enabled = str(
            environ.get("ENABLE_TRANSACTIONAL_CANARY", "false")
        ).strip().casefold() in _TRUE_VALUES
        destinations = set()
        for raw_value in str(
            environ.get("TRANSACTIONAL_CANARY_DESTINATIONS", "")
        ).split(","):
            raw_value = raw_value.strip()
            if not raw_value:
                continue
            normalized = normalize_canary_destination(raw_value)
            if normalized is None:
                diagnostic_logger.warning(
                    "Destino ignorado na configuracao do canario: %s.",
                    mask_canary_value(raw_value),
                )
                continue
            destinations.add(normalized)
        return cls(enabled=enabled, destinations=frozenset(destinations))

    def authorizes(self, destination):
        normalized = normalize_canary_destination(destination)
        return normalized is not None and normalized in self.destinations

    def active(self, transactional_delivery_enabled):
        return bool(transactional_delivery_enabled and self.enabled)
