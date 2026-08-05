from collections import defaultdict
import logging
import time

from src.stores.active import normalize_store_name

from .amazon import AmazonAffiliateProvider
from .cache import AffiliateCache
from .config import AffiliateConfig
from .manual_links import ManualAffiliateLinkLookup
from .mercado_livre import MercadoLivreAffiliateProvider
from .models import AffiliateMetrics, AffiliateResult
from .shopee import ShopeeAffiliateProvider
from .validation import validate_store_config


class AffiliateManager:
    """Unico ponto de geracao e validacao usado pelo Pipeline."""

    def __init__(
        self,
        config=None,
        cache=None,
        logger=None,
        manual_lookup=None,
    ):
        self.config = config or AffiliateConfig.from_environment()
        self.cache = cache or AffiliateCache(
            self.config.cache_path,
            self.config.cache_ttl_hours,
        )
        self.logger = logger or logging.getLogger("promobot.affiliates")
        self.manual_lookup = manual_lookup or ManualAffiliateLinkLookup()
        self.providers = {
            "mercado livre": MercadoLivreAffiliateProvider(
                self.config.mercado_livre
            ),
            "amazon": AmazonAffiliateProvider(self.config.amazon),
            "shopee": ShopeeAffiliateProvider(self.config.shopee),
        }
        self.counters = defaultdict(lambda: defaultdict(int))
        self.total_ms = 0.0

    def resolve(self, store, original_url, provided_url=""):
        started = time.perf_counter()
        store_key = normalize_store_name(store)
        provider = self.providers.get(store_key)
        self.counters[store]["requests"] += 1
        if not provider:
            return self.finish(AffiliateResult(
                store=store,
                original_url=original_url,
                status="UNSUPPORTED",
                error="loja_nao_suportada",
            ), started, "failures")
        if not original_url or not provider.valid_domain(original_url):
            return self.finish(AffiliateResult(
                store=store,
                original_url=original_url,
                provider=provider.provider_name,
                status="INVALID",
                error="url_original_invalida_para_loja",
            ), started, "invalid")

        store_config = {
            "mercado livre": self.config.mercado_livre,
            "amazon": self.config.amazon,
            "shopee": self.config.shopee,
        }[store_key]

        if provided_url:
            if provider.validate(provided_url, original_url):
                self.cache.put(
                    store, original_url, provided_url,
                    provider.provider_name, "provided",
                )
                return self.finish(AffiliateResult(
                    store=store,
                    original_url=original_url,
                    affiliate_url=provided_url,
                    provider=provider.provider_name,
                    status="PROVIDED",
                    source="provided",
                ), started, "provided")
            return self.finish(AffiliateResult(
                store=store,
                original_url=original_url,
                provider=provider.provider_name,
                status="INVALID",
                error="link_afiliado_fornecido_invalido",
            ), started, "invalid")

        manual_url, manual_source = self.manual_lookup.resolve(
            store, original_url
        )
        if manual_url and provider.validate(manual_url, original_url):
            self.cache.put(
                store,
                original_url,
                manual_url,
                provider.provider_name,
                manual_source,
            )
            return self.finish(AffiliateResult(
                store=store,
                original_url=original_url,
                affiliate_url=manual_url,
                provider=provider.provider_name,
                status="GENERATED",
                source=manual_source,
            ), started, "generated")

        cached = self.cache.get(store, original_url)
        if cached and provider.validate(
            cached["affiliate_url"], original_url
        ):
            return self.finish(AffiliateResult(
                store=store,
                original_url=original_url,
                affiliate_url=cached["affiliate_url"],
                provider=cached["provider"],
                status="CACHED",
                source=cached["source"],
                cache_hit=True,
            ), started, "cache_hits")

        configuration = validate_store_config(
            store, store_config, provider
        )
        if not configuration.generation_available:
            return self.finish(AffiliateResult(
                store=store,
                original_url=original_url,
                provider=provider.provider_name,
                status=configuration.status,
                error=configuration.reason,
            ), started, "failures")

        url, source, error = provider.generate(original_url)
        if error:
            if store_key == "shopee":
                failure_status = "MANUAL_CONFIGURATION_REQUIRED"
            elif store_config.mapping or store_config.template:
                failure_status = "UNAVAILABLE"
            else:
                failure_status = "NOT_CONFIGURED"
            return self.finish(AffiliateResult(
                store=store,
                original_url=original_url,
                provider=provider.provider_name,
                status=failure_status,
                source=source,
                error=error,
            ), started, "failures")
        if not provider.validate(url, original_url):
            return self.finish(AffiliateResult(
                store=store,
                original_url=original_url,
                provider=provider.provider_name,
                status="INVALID",
                source=source,
                error="link_gerado_invalido",
            ), started, "invalid")
        self.cache.put(
            store, original_url, url, provider.provider_name, source
        )
        return self.finish(AffiliateResult(
            store=store,
            original_url=original_url,
            affiliate_url=url,
            provider=provider.provider_name,
            status="GENERATED",
            source=source,
        ), started, "generated")

    def finish(self, result, started, counter):
        elapsed = round((time.perf_counter() - started) * 1000, 3)
        self.total_ms += elapsed
        self.counters[result.store][counter] += 1
        level = logging.INFO if result.valid else logging.WARNING
        self.logger.log(
            level,
            "affiliate store=%s status=%s source=%s cache=%s "
            "elapsed_ms=%.3f error=%s",
            result.store, result.status, result.source,
            result.cache_hit, elapsed, result.error,
        )
        return AffiliateResult(
            store=result.store,
            original_url=result.original_url,
            affiliate_url=result.affiliate_url,
            provider=result.provider,
            status=result.status,
            source=result.source,
            error=result.error,
            elapsed_ms=elapsed,
            cache_hit=result.cache_hit,
        )

    def metrics(self):
        by_store = {
            store: dict(values)
            for store, values in self.counters.items()
        }
        totals = defaultdict(int)
        for values in by_store.values():
            for key, value in values.items():
                totals[key] += value
        requests = totals["requests"]
        return AffiliateMetrics(
            requests=requests,
            generated=totals["generated"],
            cache_hits=totals["cache_hits"],
            provided=totals["provided"],
            failures=totals["failures"],
            invalid=totals["invalid"],
            average_ms=round(
                self.total_ms / requests, 3
            ) if requests else 0.0,
            by_store=by_store,
        )

    def close(self):
        self.cache.close()
        if self.manual_lookup:
            self.manual_lookup.close()
