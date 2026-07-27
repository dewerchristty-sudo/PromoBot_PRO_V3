import unicodedata


ACTIVE_STORE_NAMES = (
    "Mercado Livre",
    "Amazon",
    "Shopee",
)


def normalize_store_name(value):
    normalized = unicodedata.normalize("NFKD", str(value or "").casefold())
    return "".join(
        character for character in normalized
        if not unicodedata.combining(character)
    ).strip()


ACTIVE_STORE_KEYS = frozenset(
    normalize_store_name(name) for name in ACTIVE_STORE_NAMES
)


def is_active_store(value):
    return normalize_store_name(value) in ACTIVE_STORE_KEYS


def active_store_names():
    return list(ACTIVE_STORE_NAMES)


def filter_active_products(products):
    return [
        product for product in products or []
        if is_active_store(
            product.get("loja", product.get("store", ""))
        )
    ]
