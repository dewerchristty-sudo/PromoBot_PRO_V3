from datetime import datetime, timedelta, timezone

from src.promotion_hunter.contracts import PromotionSource
from src.promotion_hunter.delivery import PromotionHunterQueue
from src.promotion_hunter.models import (
    DecisionStatus, HunterDecision, NormalizedProduct,
)
from src.promotion_hunter.repository import PromotionHunterRepository


def objects():
    product = NormalizedProduct(
        "mercado livre:MLB1", "Mercado Livre", "Produto",
        external_id="MLB1", url="https://produto/1", current_price=90,
        source_ids=("kw",),
    )
    decision = HunterDecision(
        product.deduplication_key, DecisionStatus.APPROVED,
        "oferta_aprovada", 90, "excelente", "pipeline", ("kw",),
    )
    return product, decision


def test_queue_migration_is_idempotent_and_recovers_sending(tmp_path):
    repo = PromotionHunterRepository(tmp_path / "hunter.db")
    repo.migrate()
    repo.migrate()
    product, decision = objects()
    identifier = repo.enqueue_approved("run", product, decision)
    attempt = repo.start_attempt(identifier, datetime.now(timezone.utc).isoformat())
    assert attempt
    assert repo.recover_sending() == 1
    assert repo.queue_items(("failed",))[0]["status"] == "failed"
    repo.close()


def test_sent_product_is_blocked_inside_window_and_allowed_after(tmp_path):
    repo = PromotionHunterRepository(tmp_path / "hunter.db")
    repo.migrate()
    product, decision = objects()
    queue = PromotionHunterQueue(repo)
    identifier = queue.enqueue("run", product, decision)
    old = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    attempt = repo.start_attempt(identifier, old)
    repo.finish_attempt(identifier, attempt, "sent", old)
    assert queue.enqueue("run2", product, decision)
    recent_id = repo.enqueue_approved("run3", product, decision)
    now = datetime.now(timezone.utc).isoformat()
    recent_attempt = repo.start_attempt(recent_id, now)
    repo.finish_attempt(recent_id, recent_attempt, "sent", now)
    assert queue.enqueue("run4", product, decision) is None
    repo.close()
