from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.parse import urlsplit, urlunsplit

from src.price_history.money import money

from .contracts import PromotionSource
from .models import NormalizedProduct
from .categories import CATEGORY_KEYWORDS, classify_category


class ProductNormalizer:
    @staticmethod
    def _value(product: Mapping[str, Any], *names: str, default: Any = "") -> Any:
        for name in names:
            value = product.get(name)
            if value not in (None, ""):
                return value
        return default

    @staticmethod
    def _number(value: Any) -> float | None:
        if value in (None, ""):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        text = re.sub(r"[^\d,.-]", "", str(value))
        if "," in text:
            text = text.replace(".", "").replace(",", ".")
        try:
            return float(text)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _money_number(value: Any) -> float | None:
        parsed = money(value)
        return float(parsed) if parsed is not None else None

    @staticmethod
    def _canonical_url(value: str) -> str:
        if not value:
            return ""
        parts = urlsplit(value.strip())
        return urlunsplit((
            parts.scheme.casefold(),
            parts.netloc.casefold(),
            parts.path.rstrip("/"),
            "",
            "",
        ))

    @staticmethod
    def _slug(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value)
        ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
        return re.sub(r"[^a-z0-9]+", "-", ascii_value.casefold()).strip("-")

    def normalize(
        self,
        product: Mapping[str, Any],
        source: PromotionSource,
        collected_at: datetime | None = None,
    ) -> NormalizedProduct:
        store = str(self._value(product, "loja", "store", default=source.store))
        title = str(self._value(product, "titulo", "title", "nome"))
        external_id = str(
            self._value(product, "id", "product_id", "item_id", "external_id")
        )
        url = self._canonical_url(str(
            self._value(product, "url", "link", "product_url")
        ))
        key_part = external_id.strip() or url or self._slug(title)
        if not key_part:
            raise ValueError("Produto sem identidade normalizável")
        key = f"{store.strip().casefold()}:{key_part}"
        explicit_category = str(self._value(
            product, "categoria_manual", "categoria", "category"
        )).strip()
        search_term = str(source.configuration.get("keyword") or source.display_name)
        profile_id = str(source.configuration.get("profile_id") or "").strip()
        source_category = str(
            source.configuration.get("canonical_category") or ""
        ).strip()
        category = (
            source_category if source_category in CATEGORY_KEYWORDS
            else explicit_category if explicit_category in CATEGORY_KEYWORDS else ""
        )
        classification_source = "profile" if source_category == category else (
            "collector" if category else ""
        )
        if not category:
            category, classification_source = classify_category(title, search_term)
        return NormalizedProduct(
            deduplication_key=key,
            store=store,
            title=title,
            external_id=external_id,
            url=url,
            image_url=str(self._value(
                product, "imagem", "image", "image_url", "imagem_url"
            )),
            category=category,
            search_term=search_term,
            breadcrumb=str(self._value(product, "breadcrumb")),
            original_category=str(self._value(
                product, "categoria_original", "original_category"
            )),
            classification_source=classification_source,
            profile_id=profile_id,
            current_price=self._money_number(self._value(
                product, "preco_atual", "current_price", "preco"
            )),
            previous_price=self._money_number(self._value(
                product, "preco_anterior", "preco_antigo", "previous_price"
            )),
            discount_percent=self._number(self._value(
                product, "desconto_percentual", "discount_percent"
            )),
            saving_amount=self._money_number(self._value(
                product, "economia", "saving_amount"
            )),
            source_ids=(source.source_id,),
            source_types=(source.source_type,),
            collected_at=collected_at or datetime.now(timezone.utc),
            raw=dict(product),
        )
