from collections import defaultdict
from datetime import datetime, timedelta
from typing import DefaultDict, List, Optional

from .models import OfferSnapshot


class ObservationalOfferHistory:
    """Histórico consultivo: identifica repetições, mas nunca bloqueia envios."""

    def __init__(self) -> None:
        self._by_product: DefaultDict[str, List[OfferSnapshot]] = defaultdict(list)
        self._by_url: DefaultDict[str, List[OfferSnapshot]] = defaultdict(list)

    def record(self, offer: OfferSnapshot) -> None:
        self._by_product[offer.product_key].append(offer)
        self._by_url[offer.url].append(offer)

    def product_seen(self, product_key: str) -> bool:
        return bool(self._by_product.get(product_key))

    def link_seen(self, url: str) -> bool:
        return bool(self._by_url.get(url))

    def most_recent(self, product_key: str) -> Optional[OfferSnapshot]:
        offers = self._by_product.get(product_key, [])
        return max(offers, key=lambda item: item.captured_at) if offers else None

    def seen_since(
        self,
        product_key: str,
        period: timedelta,
        now: Optional[datetime] = None,
    ) -> bool:
        recent = self.most_recent(product_key)
        reference = now or datetime.now()
        return bool(recent and recent.captured_at >= reference - period)
