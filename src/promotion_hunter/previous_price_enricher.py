from __future__ import annotations

import logging
import time
from typing import Any

from src.stores.mercado_livre import MercadoLivre

logger = logging.getLogger(__name__)

ENRICH_TIMEOUT_SECONDS = 15
MAX_ENRICHMENTS_PER_CYCLE = 10
CACHE_TTL_SECONDS = 24 * 3600


class PreviousPriceEnricher:
    def __init__(self, browser_manager=None, timeout=ENRICH_TIMEOUT_SECONDS,
                 max_per_cycle=MAX_ENRICHMENTS_PER_CYCLE, cache_ttl=CACHE_TTL_SECONDS):
        self._timeout = timeout
        self._max_per_cycle = max_per_cycle
        self._cache_ttl = cache_ttl
        self._browser_manager = browser_manager
        self._store = None
        self._cache = {}
        self._enrich_count = 0

    @staticmethod
    def _canonical_url(url):
        from urllib.parse import urlparse
        if not url:
            return ""
        parts = urlparse(str(url).strip())
        return (parts.netloc.casefold() + parts.path.rstrip("/").casefold())

    def _is_cached(self, url):
        key = self._canonical_url(url)
        entry = self._cache.get(key)
        if entry is None:
            return False
        return (time.monotonic() - entry[0]) < self._cache_ttl

    def _cache_get(self, url):
        key = self._canonical_url(url)
        entry = self._cache.get(key)
        return entry[1] if entry else None

    def _cache_set(self, url, price):
        self._cache[self._canonical_url(url)] = (time.monotonic(), price)

    def _get_store(self):
        if self._store is None:
            self._store = MercadoLivre(browser_manager=self._browser_manager)
        return self._store

    def enrich(self, product):
        store = str(product.get("loja") or product.get("store") or "").casefold()
        if "mercado" not in store and "livre" not in store:
            return product

        cur = product.get("current_price") or product.get("preco_atual") or 0
        try:
            cur = float(cur)
        except (TypeError, ValueError):
            return product
        if cur <= 0:
            return product

        existing = (product.get("previous_price") or product.get("preco_anterior")
                     or product.get("preco_antigo"))
        if existing:
            try:
                if float(existing) > cur:
                    return product
            except (TypeError, ValueError):
                pass

        url = product.get("product_url") or product.get("url") or product.get("link") or ""
        if not url:
            return product

        if self._is_cached(url):
            cached = self._cache_get(url)
            if cached is not None and cached > cur:
                return self._apply(product, cached, cur)
            return product

        if self._enrich_count >= self._max_per_cycle:
            return product
        self._enrich_count += 1

        try:
            store_obj = self._get_store()
            start = time.perf_counter()
            page_data = store_obj.product_from_url(url)
            elapsed = time.perf_counter() - start
            logger.info("Enrich ML: url=%s time=%.2fs", self._canonical_url(url), elapsed)

            old_price_text = page_data.get("preco_antigo", "")
            if not old_price_text:
                self._cache_set(url, None)
                return product

            new_old = self._parse_price(old_price_text)
            if new_old is None:
                self._cache_set(url, None)
                return product

            if new_old > cur:
                self._cache_set(url, new_old)
                product["previous_price"] = new_old
                product["preco_antigo"] = old_price_text
                savings = round(new_old - cur, 2)
                discount = round(((new_old - cur) / new_old) * 100, 2)
                product["savings"] = savings
                product["discount_percent"] = discount
                logger.info("Enrich OK: cur=%s prev=%s saving=%s discount=%s%%",
                            cur, new_old, savings, discount)
            else:
                self._cache_set(url, None)
        except Exception as exc:
            logger.warning("Enrich failed (non-blocking): %s", str(exc)[:200])
            self._cache_set(url, None)

        return product

    @staticmethod
    def _parse_price(value):
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value) if value > 0 else None
        text = str(value).strip().replace("R$", "").replace(" ", "")
        if "," in text and "." in text:
            if text.rfind(",") > text.rfind("."):
                text = text.replace(".", "").replace(",", ".")
            else:
                text = text.replace(",", "")
        elif "," in text:
            text = text.replace(".", "").replace(",", ".")
        try:
            return float(text) if float(text) > 0 else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _apply(product, old_price, current_price):
        if old_price <= current_price:
            return product
        product["previous_price"] = old_price
        savings = round(old_price - current_price, 2)
        discount = round(((old_price - current_price) / old_price) * 100, 2)
        product["savings"] = savings
        product["discount_percent"] = discount
        return product

    def reset_count(self):
        self._enrich_count = 0