from datetime import timedelta, timezone
from decimal import Decimal
import hashlib

from src.affiliates.validation import product_identity

from .analyzer import PriceHistoryAnalyzer
from .money import money, percent_change
from .models import ObservationDecision


class RealPriceHistoryService:

    REAL_SOURCES = {
        "mercado_livre_persistent_browser",
        "amazon_live_collection",
        "shopee_live_collection",
    }

    def __init__(self, repository, config):
        self.repository = repository
        self.config = config
        self.analyzer = PriceHistoryAnalyzer(config)

    def record(self, observation, dry_run=False):
        observed_at = observation.observed_at.astimezone(timezone.utc)
        price = money(observation.price)
        key_from_url = product_identity(
            observation.store, observation.original_url
        )
        reason = ""
        if not observation.product_key or key_from_url != observation.product_key:
            reason = "PRODUCT_IDENTITY_MISMATCH"
        elif price is None or price <= 0:
            reason = "INVALID_PRICE"
        elif observation.currency != "BRL":
            reason = "INVALID_CURRENCY"
        elif observation.store != "Mercado Livre":
            reason = "STORE_MISMATCH"
        elif not observation.original_url.startswith("https://"):
            reason = "INVALID_URL"
        elif observation.source not in self.REAL_SOURCES:
            reason = "NON_REAL_SOURCE"
        history = self.repository.real_price_history(
            observation.product_key
        ) if not reason else []
        if not reason and history:
            latest_at = self.repository.datetime(history[-1]["observed_at"])
            elapsed = observed_at - latest_at
            latest_price = money(history[-1]["price"])
            if (
                elapsed < timedelta(
                    minutes=self.config.duplicate_window_minutes
                ) and latest_price == price
            ):
                reason = "DUPLICATE_WITHIN_WINDOW"
            elif elapsed < timedelta(
                minutes=self.config.min_interval_minutes
            ):
                reason = "MIN_INTERVAL_NOT_REACHED"
            else:
                med = self.analyzer.analyze(
                    observation.product_key, history
                ).median
                variation = percent_change(price, med)
                if (
                    variation is not None
                    and abs(variation)
                    > Decimal(str(self.config.outlier_percent))
                ):
                    reason = "OUTLIER_PERCENT"
        raw_hash = (
            f"{observation.store}|{observation.product_key}|{price}|"
            f"{observed_at.isoformat()}|{observation.run_id}"
        )
        observation_hash = hashlib.sha256(
            raw_hash.encode("utf-8")
        ).hexdigest()
        record = {
            "product_key": observation.product_key,
            "canonical_identity": observation.canonical_identity,
            "canonical_product_id": observation.canonical_product_id,
            "canonical_url": observation.canonical_url,
            "store": observation.store, "title": observation.title,
            "price": price or "", "currency": observation.currency,
            "original_url": observation.original_url,
            "image_url": observation.image_url,
            "availability": observation.availability,
            "source": observation.source, "run_id": observation.run_id,
            "observed_at": observed_at.isoformat(),
            "observation_hash": observation_hash,
        }
        if reason:
            if not dry_run:
                self.repository.record_price_rejection({
                    **record, "reason": reason
                })
            return ObservationDecision(
                False, False, "REJECTED", reason, observation_hash,
                observation.product_key, price, dry_run,
            )
        stored = False if dry_run else (
            self.repository.add_real_price_observation(record)
        )
        return ObservationDecision(
            True, stored, "WOULD_STORE" if dry_run else "STORED",
            "", observation_hash, observation.product_key, price, dry_run,
        )

    def analyze(self, product_key):
        return self.analyzer.analyze(
            product_key,
            self.repository.real_price_history(product_key),
            self.repository.price_history_rejections(product_key),
        )
