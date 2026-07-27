from urllib.parse import quote

from .base import AffiliateProvider


class ShopeeAffiliateProvider(AffiliateProvider):
    store_name = "Shopee"
    provider_name = "Shopee Afiliados"
    allowed_domains = (
        "shopee.com.br",
        "s.shopee.com.br",
        "br.shp.ee",
    )

    def generate(self, original_url):
        mapped = self.mapped(original_url)
        if mapped:
            return mapped, "official_map", ""
        if not self.config.template:
            return "", "", "integracao_oficial_nao_configurada"
        try:
            return self.config.template.format(
                url=original_url,
                url_encoded=quote(original_url, safe=""),
                affiliate_id=self.config.affiliate_id,
            ), "official_template", ""
        except (KeyError, ValueError) as error:
            return "", "", str(error)
