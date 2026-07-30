from datetime import datetime, timedelta, timezone


class PromotionHunterQueue:
    def __init__(self, repository, duplicate_window_hours=24):
        self.repository = repository
        self.duplicate_window_hours = duplicate_window_hours

    def enqueue(self, run_id, product, decision):
        since = (
            datetime.now(timezone.utc)
            - timedelta(hours=self.duplicate_window_hours)
        ).isoformat()
        if self.repository.recently_sent(product.deduplication_key, since):
            return None
        return self.repository.enqueue_approved(run_id, product, decision)

    def pending(self, limit=100):
        return self.repository.queue_items(("pending", "failed"), limit)

    def recover(self):
        return self.repository.recover_sending()
