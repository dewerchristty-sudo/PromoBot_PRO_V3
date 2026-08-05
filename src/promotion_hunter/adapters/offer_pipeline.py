from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EmptySchedulerDecision:
    selected_offers: tuple = ()
    skipped_offers: tuple = ()
    selected_count: int = 0


class InertOfferScheduler:
    def run(self, now=None):
        return EmptySchedulerDecision()


class PromotionHunterOfferPipelineAdapter:
    def __init__(self, pipeline):
        self.pipeline = pipeline

    @staticmethod
    def _canonical_payload(product):
        payload = dict(product)
        if "preco" in product:
            payload["raw_price"] = product["preco"]
        if "preco_antigo" in product:
            payload["raw_previous_price"] = product["preco_antigo"]
        payload["current_price"] = product.get("preco_atual")
        previous_price = (
            product.get("preco_anterior")
            or product.get("previous_price")
            or product.get("preco_antigo")
        )
        payload["previous_price"] = previous_price
        payload["savings"] = product.get("economia")
        payload["discount_percent"] = product.get("desconto_percentual")
        payload["profile_id"] = product.get("profile_id", "")
        return payload

    def process_batch(self, products):
        return self.pipeline.process_batch([
            self._canonical_payload(product) for product in products
        ])

    def close(self):
        closer = getattr(self.pipeline, "close", None)
        if callable(closer):
            closer()


def build_controlled_offer_pipeline(database_path, affiliate_config=None):
    from src.affiliates import AffiliateManager
    from src.database.offer_pipeline_repository import OfferPipelineRepository
    from src.offers.pipeline import OfferPipeline

    repository = OfferPipelineRepository(Path(database_path))
    repository.migrate()
    affiliate_manager = (
        AffiliateManager(affiliate_config) if affiliate_config is not None
        else None
    )
    return PromotionHunterOfferPipelineAdapter(OfferPipeline(
        repository=repository,
        scheduler=InertOfferScheduler(),
        affiliate_manager=affiliate_manager,
    ))
