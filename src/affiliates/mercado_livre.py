import re
from urllib.parse import quote

from src.stores.mercado_livre import MercadoLivre

from .base import AffiliateProvider


class MercadoLivreAffiliateProvider(AffiliateProvider):
    store_name = "Mercado Livre"
    provider_name = "Mercado Livre Afiliados"
    allowed_domains = (
        "mercadolivre.com.br",
        "mercadolivre.com",
        "meli.la",
    )

    def generate(self, original_url):
        mapped = self.mapped(original_url)
        if mapped:
            return mapped, "official_map", ""
        if not self.config.template:
            return "", "", (
                "produto_sem_link_oficial_no_mapa"
                if self.config.mapping
                else "integracao_oficial_nao_configurada"
            )
        match = re.search(
            r"\b(MLBU?-?\d+)\b", original_url, re.IGNORECASE
        )
        product_id = MercadoLivre.normalize_product_id(
            match.group(1) if match else ""
        )
        try:
            return self.config.template.format(
                url=original_url,
                url_encoded=quote(original_url, safe=""),
                affiliate_id=self.config.affiliate_id,
                product_id=product_id,
            ), "official_template", ""
        except (KeyError, ValueError) as error:
            return "", "", str(error)
