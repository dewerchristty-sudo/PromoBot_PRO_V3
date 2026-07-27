from abc import ABC, abstractmethod
import re
from urllib.parse import urlparse

from .validation import preserves_product, safe_absolute_url


class AffiliateProvider(ABC):
    store_name = ""
    provider_name = ""
    allowed_domains = ()

    def __init__(self, config):
        self.config = config

    @abstractmethod
    def generate(self, original_url):
        """Retorna (url, source, error)."""
        raise NotImplementedError

    def valid_domain(self, url):
        try:
            host = (urlparse(url).hostname or "").casefold()
        except ValueError:
            return False
        return any(
            host == domain or host.endswith("." + domain)
            for domain in self.allowed_domains
        )

    def validate(self, url, original_url):
        return bool(
            safe_absolute_url(url, self.allowed_domains)
            and url != original_url
            and preserves_product(self.store_name, original_url, url)
        )

    @staticmethod
    def mapping_entries(mapping):
        result = []
        for part in str(mapping or "").replace("\n", "").split(";"):
            if "=" in part:
                key, value = part.split("=", 1)
                result.append((key.strip(), value.strip()))
        return result

    def mapped(self, original_url):
        normalized = re.sub(
            r"[^a-z0-9]", "", original_url.casefold()
        )
        for key, url in self.mapping_entries(self.config.mapping):
            key = re.sub(r"[^a-z0-9]", "", key.casefold())
            if key and key in normalized:
                return url
        return ""
