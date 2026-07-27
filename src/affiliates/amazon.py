from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .base import AffiliateProvider
from .validation import amazon_tag_from_url, is_placeholder


class AmazonAffiliateProvider(AffiliateProvider):
    store_name = "Amazon"
    provider_name = "Amazon Associados"
    allowed_domains = ("amazon.com.br", "amzn.to")

    def validate(self, url, original_url):
        if not super().validate(url, original_url):
            return False
        parsed = urlparse(url)
        if (parsed.hostname or "").casefold().endswith("amzn.to"):
            return True
        tag = amazon_tag_from_url(url)
        if not tag or is_placeholder(tag):
            return False
        return not self.config.associate_tag or tag == self.config.associate_tag

    def generate(self, original_url):
        mapped = self.mapped(original_url)
        if mapped:
            return mapped, "official_map", ""
        if self.config.template:
            try:
                return self.config.template.format(
                    url=original_url,
                    affiliate_id=self.config.affiliate_id,
                    associate_tag=self.config.associate_tag,
                ), "official_template", ""
            except (KeyError, ValueError) as error:
                return "", "", str(error)
        tag = self.config.associate_tag
        if not tag:
            return "", "", "associate_tag_nao_configurada"
        parsed = urlparse(original_url)
        if not self.valid_domain(original_url) or parsed.hostname == "amzn.to":
            return "", "", "url_original_amazon_nao_expansivel"
        query = [
            (key, value) for key, value in parse_qsl(parsed.query)
            if key.casefold() != "tag"
        ]
        query.append(("tag", tag))
        return urlunparse(parsed._replace(
            query=urlencode(query)
        )), "associate_tag", ""
