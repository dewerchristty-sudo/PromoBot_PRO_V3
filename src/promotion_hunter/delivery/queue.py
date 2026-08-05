from datetime import datetime, timedelta, timezone

from ..config import MAX_DELIVERY_ATTEMPTS
from ..categories import classify_category


class PromotionHunterQueue:
    def __init__(self, repository, duplicate_window_hours=24):
        self.repository = repository
        self.duplicate_window_hours = duplicate_window_hours
        self._profile_cursor = 0

    def enqueue(self, run_id, product, decision):
        since = (
            datetime.now(timezone.utc)
            - timedelta(hours=self.duplicate_window_hours)
        ).isoformat()
        lookup = getattr(
            self.repository, "active_or_recent", self.repository.recently_sent
        )
        try:
            existing = lookup(
                product.deduplication_key, since, MAX_DELIVERY_ATTEMPTS
            )
        except TypeError:
            existing = lookup(product.deduplication_key, since)
        payload = dict(getattr(decision, "delivery_payload", {}) or {})
        try:
            previous_signature = existing["promotion_signature"] if existing else ""
        except (KeyError, IndexError, TypeError):
            previous_signature = ""
        legitimate_new_promotion = (
            payload.get("duplicate_type") == "nova_promocao"
            and payload.get("promotion_signature")
            and (
                not existing
                or previous_signature != payload.get("promotion_signature")
            )
        )
        if existing and not legitimate_new_promotion:
            return None
        return self.repository.enqueue_approved(run_id, product, decision)

    def pending(self, limit=100, after=None, run_id=None, approved_since=None):
        rows = self.repository.queue_items(
            ("pending", "failed"), max(int(limit), 1000),
            max_attempts=MAX_DELIVERY_ATTEMPTS,
            after=after, run_id=run_id, approved_since=approved_since,
        )
        ordered = self._fair_order(rows, self._profile_cursor)
        if ordered:
            self._profile_cursor = (self._profile_cursor + max(1, int(limit)))
        return ordered[:limit]

    @staticmethod
    def _fair_order(rows, cursor=0):
        """Round-robin por perfil lógico, mantendo FIFO em cada perfil."""
        buckets = {}
        order = []
        for row in rows:
            try:
                profile_id = str(row["profile_id"] or "").strip()
            except (KeyError, IndexError):
                profile_id = ""
            category = str(row["category"] or "").strip()
            if not category:
                category, _ = classify_category(
                    str(row["title"] or ""), str(row["search_term"] or "")
                )
            key = (
                profile_id or category or "perfil_desconhecido",
                str(row["store"] or ""),
            )
            if key not in buckets:
                buckets[key] = []
                order.append(key)
            buckets[key].append(row)
        result = []
        if order:
            start = int(cursor) % len(order)
            order = order[start:] + order[:start]
        while order:
            next_order = []
            for key in order:
                bucket = buckets[key]
                if bucket:
                    result.append(bucket.pop(0))
                if bucket:
                    next_order.append(key)
            order = next_order
        return tuple(result)

    def recover(self):
        return self.repository.recover_sending()
