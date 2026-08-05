from __future__ import annotations

import json
import re
from collections.abc import Iterable
from urllib.parse import urlparse


MAX_AMAZON_IMAGE_CANDIDATES = 8
_TRANSFORM = re.compile(
    r"\._(?=[A-Z0-9_,]*?(?:AC_|SX|SY|UX|UY|UL|SL))"
    r"[A-Z0-9_,]+_\.(?=[A-Za-z0-9]+(?:[?#]|$))",
    re.IGNORECASE,
)


def is_amazon_image_url(url: str) -> bool:
    host = (urlparse(str(url or "")).hostname or "").casefold()
    return host == "media-amazon.com" or host.endswith(".media-amazon.com") \
        or host == "images-amazon.com" or host.endswith(".images-amazon.com")


def original_amazon_image_url(url: str) -> str:
    value = str(url or "").strip()
    if not is_amazon_image_url(value):
        return value
    return _TRANSFORM.sub(".", value, count=1)


def _srcset_urls(value: str) -> list[str]:
    ranked = []
    for index, part in enumerate(str(value or "").split(",")):
        fields = part.strip().split()
        if not fields:
            continue
        score = 0.0
        if len(fields) > 1:
            descriptor = fields[-1].casefold()
            try:
                score = float(descriptor[:-1]) * (1000 if descriptor.endswith("x") else 1)
            except (TypeError, ValueError):
                score = 0.0
        ranked.append((score, -index, fields[0]))
    return [url for _score, _index, url in sorted(ranked, reverse=True)]


def _dynamic_urls(value: str) -> list[str]:
    try:
        payload = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict):
        return []
    ranked = []
    for index, (url, dimensions) in enumerate(payload.items()):
        if not isinstance(dimensions, (list, tuple)) or len(dimensions) < 2:
            continue
        try:
            area = int(dimensions[0]) * int(dimensions[1])
        except (TypeError, ValueError):
            area = 0
        ranked.append((area, -index, str(url)))
    return [url for _area, _index, url in sorted(ranked, reverse=True)]


def amazon_image_candidates(
    urls: Iterable[str] = (), *, srcset: str = "", old_hires: str = "",
    dynamic_image: str = "", limit: int = MAX_AMAZON_IMAGE_CANDIDATES,
) -> list[str]:
    raw = [
        str(old_hires or "").strip(),
        *_dynamic_urls(dynamic_image),
        *_srcset_urls(srcset),
        *(str(url or "").strip() for url in urls),
    ]
    raw = [url for url in raw if url]
    preferred = []
    fallbacks = []
    for url in raw:
        original = original_amazon_image_url(url)
        if original != url:
            preferred.append(original)
            fallbacks.append(url)
        else:
            preferred.append(url)
    ordered = []
    for url in (*preferred, *fallbacks):
        if url not in ordered:
            ordered.append(url)
    return ordered[:max(1, int(limit))]


def amazon_image_candidates_from_element(image) -> list[str]:
    if image is None:
        return []
    return amazon_image_candidates(
        (image.get("src", ""), image.get("data-src", "")),
        srcset=image.get("srcset", "") or image.get("data-srcset", ""),
        old_hires=image.get("data-old-hires", ""),
        dynamic_image=image.get("data-a-dynamic-image", ""),
    )
