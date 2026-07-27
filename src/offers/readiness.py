from dataclasses import dataclass
import re

from src.affiliates import AffiliateManager
from .score import OfferScore


@dataclass(frozen=True, slots=True)
class ReadinessResult:
    product: dict
    analytical_inputs: dict
    operational_readiness: dict


class OfferReadinessEnricher:
    AFFILIATE_REQUIRED = {"mercado livre", "shopee", "amazon"}
    TRUSTED_STORES = {"amazon", "mercado livre", "shopee"}

    def __init__(self, affiliate_manager=None):
        self.affiliate_manager = affiliate_manager or AffiliateManager()

    def prepare(self, product):
        value = dict(product or {})
        store = str(value.get("loja", value.get("store", "")) or "")
        store_key = store.strip().casefold()
        original = str(
            value.get("original_url") or value.get("product_link")
            or value.get("link") or ""
        ).strip()
        provided = str(
            value.get("affiliate_url") or value.get("affiliate_link") or ""
        ).strip()
        affiliate_result = self.affiliate_manager.resolve(
            store, original, provided
        )
        affiliate = affiliate_result.affiliate_url
        image, image_source = self.image(value)
        current = OfferScore.number(
            value.get(
                "current_price",
                value.get("preco_valor", value.get("preco")),
            )
        )
        previous = OfferScore.number(
            value.get("previous_price", value.get("preco_antigo"))
        )
        discount = OfferScore.discount_percent(current, previous)
        required = store_key in self.AFFILIATE_REQUIRED
        blocks = []
        if not original:
            blocks.append("link_original_ausente")
        if required and not affiliate:
            blocks.append("link_afiliado_ausente")
        if not image:
            blocks.append("imagem_ausente")
        future = dict(value.get("future_signals") or {})
        future.update({
            "original_url": original,
            "affiliate_url": affiliate,
            "affiliate_provider": affiliate_result.provider,
            "affiliate_status": affiliate_result.status,
            "affiliate_error": affiliate_result.error,
            "affiliate_required": required,
            "affiliate_source": affiliate_result.source,
            "affiliate_cache_hit": affiliate_result.cache_hit,
            "affiliate_elapsed_ms": affiliate_result.elapsed_ms,
            "image_url": image,
            "image_source": image_source,
            "image_status": "AVAILABLE" if image else "MISSING",
            "image_error": "" if image else "imagem_nao_encontrada",
            "current_price": current,
            "previous_price": previous,
            "discount_percent": discount,
            "discount_source": (
                "preco_anterior_anunciado" if discount > 0 else "indisponivel"
            ),
            "price_status": "VALID" if current > 0 else "INVALID",
            "currency": "BRL",
            "title_quality": self.title_quality(
                str(value.get("titulo", value.get("title", "")) or "")
            ),
            "operational_blocks": tuple(blocks),
        })
        value.update({
            "original_url": original,
            "product_link": original,
            "affiliate_url": affiliate,
            "affiliate_link": affiliate,
            "affiliate_provider": affiliate_result.provider,
            "affiliate_status": affiliate_result.status,
            "affiliate_error": affiliate_result.error,
            "image_url": image,
            "image_source": image_source,
            "image_status": future["image_status"],
            "image_error": future["image_error"],
            "current_price": current,
            "previous_price": previous,
            "discount_percent": discount,
            "discount_source": future["discount_source"],
            "price_status": future["price_status"],
            "currency": "BRL",
            "trusted_store": store_key in self.TRUSTED_STORES,
            "future_signals": future,
        })
        return ReadinessResult(value, {
            "current_price": current,
            "previous_price": previous,
            "discount_percent": discount,
            "title_quality": future["title_quality"],
            "trusted_store": value["trusted_store"],
            "image_available": bool(image),
            "original_link_available": bool(original),
            "affiliate_link_available": bool(affiliate),
        }, {
            "ready": not blocks,
            "blocks": tuple(blocks),
            "affiliate_status": affiliate_result.status,
            "image_status": future["image_status"],
            "price_status": future["price_status"],
        })

    @staticmethod
    def image(product):
        for source, raw in (
            ("image_url", product.get("image_url")),
            ("imagem", product.get("imagem")),
            ("data-src", product.get("data-src")),
            ("srcset", product.get("srcset")),
            ("data-srcset", product.get("data-srcset")),
            ("json_ld", product.get("json_ld_image")),
            ("open_graph", product.get("og_image")),
        ):
            url = str(raw or "").strip().split()[0] if raw else ""
            if url.startswith(("https://", "http://")):
                return url, source
        return "", ""

    @staticmethod
    def title_quality(title):
        words = [word for word in re.split(r"\W+", title) if word]
        if len(title.strip()) >= 20 and len(words) >= 4:
            return "GOOD"
        if len(title.strip()) >= 8:
            return "ACCEPTABLE"
        return "POOR"
