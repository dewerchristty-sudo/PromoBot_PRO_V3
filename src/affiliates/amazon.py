import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .base import AffiliateProvider
from .validation import amazon_tag_from_url, is_placeholder, mask_secret


MIN_ASSOCIATE_TAG_LENGTH = 3
MAX_ASSOCIATE_TAG_LENGTH = 64


def validate_associate_tag(value):
    """Valida uma Associate Tag sem incluir o valor em erros."""

    tag = str(value or "")
    if not tag:
        raise ValueError("Amazon Associate Tag ausente.")
    if tag != tag.strip() or any(character.isspace() for character in tag):
        raise ValueError("Amazon Associate Tag invalida: contem espacos.")
    if any(ord(character) < 32 or ord(character) == 127 for character in tag):
        raise ValueError(
            "Amazon Associate Tag invalida: contem caractere de controle."
        )
    if not MIN_ASSOCIATE_TAG_LENGTH <= len(tag) <= MAX_ASSOCIATE_TAG_LENGTH:
        raise ValueError("Amazon Associate Tag invalida: comprimento.")
    lowered = tag.casefold()
    if (
        is_placeholder(tag)
        or "tag=" in lowered
        or "://" in lowered
        or "amazon." in lowered
        or any(character in tag for character in "\"'&=?/#\\")
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", tag)
    ):
        raise ValueError("Amazon Associate Tag invalida: formato.")
    return tag


def masked_associate_tag(value):
    tag = validate_associate_tag(value)
    if "-" in tag:
        prefix, suffix = tag.rsplit("-", 1)
        visible = prefix[:3]
        return f"{visible}***-{suffix}"
    return mask_secret(tag)


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
        try:
            tag = validate_associate_tag(tag)
        except ValueError:
            return "", "", "associate_tag_invalida"
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
