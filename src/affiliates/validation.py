from dataclasses import dataclass, field
import os
import re
from urllib.parse import parse_qs, urlparse

from src.stores.active import normalize_store_name


DEFAULT_PLACEHOLDERS = {
    "sua_tag", "seu_id", "token_aqui", "example", "exemplo", "teste",
    "placeholder", "changeme", "xxx", "123456", "your_tag", "your_id",
}
STATUSES = {
    "NOT_CONFIGURED", "PARTIALLY_CONFIGURED", "CONFIGURED",
    "VALIDATION_FAILED", "VALIDATED", "UNAVAILABLE",
    "MANUAL_CONFIGURATION_REQUIRED",
}


@dataclass(frozen=True, slots=True)
class StoreValidation:
    store: str
    status: str
    configured: bool
    validated: bool
    generation_available: bool
    reason: str
    missing: tuple[str, ...] = ()
    masked_values: dict[str, str] = field(default_factory=dict)
    session_status: str = ""


def placeholder_values():
    configured = os.getenv("AFFILIATE_PLACEHOLDER_VALUES", "")
    return DEFAULT_PLACEHOLDERS | {
        value.strip().casefold()
        for value in configured.split(",") if value.strip()
    }


def is_placeholder(value):
    normalized = str(value or "").strip().casefold()
    if not normalized:
        return False
    compact = re.sub(r"[^a-z0-9_]+", "", normalized)
    return any(
        marker == normalized
        or marker == compact
        or marker in normalized
        for marker in placeholder_values()
    )


def mask_secret(value):
    value = str(value or "").strip()
    if not value:
        return "(ausente)"
    if len(value) <= 4:
        return "*" * len(value)
    return f"{value[:2]}{'*' * min(len(value) - 4, 8)}{value[-2:]}"


def safe_absolute_url(url, allowed_domains, max_length=2048):
    value = str(url or "").strip()
    if not value or len(value) > max_length:
        return False
    if any(token in value for token in ("{", "}", "<", ">")):
        return False
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    if parsed.scheme.casefold() != "https" or not parsed.hostname:
        return False
    host = parsed.hostname.casefold()
    unsafe_parts = [
        part for part in re.split(r"[/&=?#]+", parsed.path + "?" + parsed.query)
        if part
    ]
    configured_placeholders = placeholder_values()
    if any(
        part.casefold() in configured_placeholders
        or re.sub(r"[^a-z0-9_]+", "", part.casefold())
        in configured_placeholders
        for part in unsafe_parts
    ):
        return False
    return any(
        host == domain or host.endswith("." + domain)
        for domain in allowed_domains
    )


def product_identity(store, url):
    value = str(url or "")
    key = normalize_store_name(store)
    if key == "amazon":
        match = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", value, re.I)
        return match.group(1).upper() if match else ""
    if key == "mercado livre":
        match = re.search(r"\b(MLB)-?(\d+)\b", value, re.I)
        return "".join(match.groups()).upper() if match else ""
    if key == "shopee":
        match = re.search(r"(?:-i\.|/product/)(\d+)[./](\d+)", value, re.I)
        return ".".join(match.groups()) if match else ""
    return ""


def preserves_product(store, original_url, affiliate_url):
    original = product_identity(store, original_url)
    generated = product_identity(store, affiliate_url)
    if original and generated:
        return original == generated
    host = (urlparse(affiliate_url).hostname or "").casefold()
    opaque_official = {
        "mercado livre": ("meli.la",),
        "amazon": ("amzn.to",),
        "shopee": ("s.shopee.com.br", "br.shp.ee"),
    }.get(normalize_store_name(store), ())
    return any(host == domain or host.endswith("." + domain)
               for domain in opaque_official)


def template_fields(template):
    return set(re.findall(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}", template or ""))


def validate_store_config(store, config, provider):
    key = normalize_store_name(store)
    values = {
        "affiliate_id": config.affiliate_id,
        "associate_tag": config.associate_tag,
        "mapping": config.mapping,
        "template": config.template,
        "api_url": config.api_url,
        "api_token": config.api_token,
    }
    present = {name: value for name, value in values.items() if value}
    masked = {
        name: mask_secret(value)
        for name, value in present.items()
        if name in {"affiliate_id", "associate_tag", "api_token"}
    }
    sensitive_values = (
        config.affiliate_id, config.associate_tag,
        config.api_token, config.template, config.api_url,
    )
    if any(is_placeholder(value) for value in sensitive_values if value):
        return StoreValidation(
            store, "VALIDATION_FAILED", True, False, False,
            "configuracao_contem_valor_ficticio", masked_values=masked,
        )
    if key == "amazon":
        if not present:
            return StoreValidation(
                store, "NOT_CONFIGURED", False, False, False,
                "associate_tag_ausente", ("AMAZON_ASSOCIATE_TAG",), masked,
            )
        if not config.associate_tag and not config.mapping and not config.template:
            return StoreValidation(
                store, "PARTIALLY_CONFIGURED", True, False, False,
                "metodo_de_geracao_ausente",
                ("AMAZON_ASSOCIATE_TAG",), masked,
            )
    elif key == "mercado livre":
        if not present:
            return StoreValidation(
                store, "NOT_CONFIGURED", False, False, False,
                "mapa_ou_template_oficial_ausente",
                ("MERCADOLIVRE_AFFILIATE_MAP",
                 "MERCADOLIVRE_AFFILIATE_TEMPLATE"), masked,
            )
        if not config.mapping and not config.template:
            return StoreValidation(
                store, "PARTIALLY_CONFIGURED", True, False, False,
                "mapa_ou_template_oficial_ausente",
                ("MERCADOLIVRE_AFFILIATE_MAP",
                 "MERCADOLIVRE_AFFILIATE_TEMPLATE"), masked,
            )
    elif key == "shopee":
        if not config.mapping and not config.template:
            status = ("PARTIALLY_CONFIGURED" if present
                      else "MANUAL_CONFIGURATION_REQUIRED")
            return StoreValidation(
                store, status, bool(present), False, False,
                "metodo_oficial_manual_necessario",
                ("SHOPEE_AFFILIATE_MAP",
                 "SHOPEE_AFFILIATE_TEMPLATE"), masked,
            )

    if config.template:
        fields = template_fields(config.template)
        allowed = {"url", "url_encoded", "affiliate_id",
                   "associate_tag", "product_id"}
        if fields - allowed or ("affiliate_id" in fields
                                and not config.affiliate_id):
            return StoreValidation(
                store, "VALIDATION_FAILED", True, False, False,
                "template_invalido_ou_incompleto", masked_values=masked,
            )
    if config.mapping:
        entries = provider.mapping_entries(config.mapping)
        if not entries or any(
            not key_value or not safe_absolute_url(url, provider.allowed_domains)
            for key_value, url in entries
        ):
            return StoreValidation(
                store, "VALIDATION_FAILED", True, False, False,
                "mapa_oficial_invalido", masked_values=masked,
            )
    return StoreValidation(
        store, "CONFIGURED", True, False, True,
        "configuracao_presente_aguardando_teste_de_geracao",
        masked_values=masked,
    )


def amazon_tag_from_url(url):
    return parse_qs(urlparse(url).query).get("tag", [""])[0]
