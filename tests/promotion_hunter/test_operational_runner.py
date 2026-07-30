import os
from datetime import datetime, timezone

from src.promotion_hunter.delivery import DeliveryPolicy
from src.promotion_hunter.models import (
    DecisionStatus, HunterDecision, HunterRunResult, NormalizedProduct,
)
from src.promotion_hunter.runner import PromotionHunterRunner


class FakeRepository:
    def __init__(self):
        self.rows = []
    def sent_count_since(self, since): return 0
    def last_sent_at(self): return None
    def start_attempt(self, identifier, started): return 1
    def finish_attempt(self, *args): self.rows.append(args)


class FakeQueue:
    def __init__(self):
        self.rows = []
        self.recovered = 0
    def recover(self):
        self.recovered += 1
        return 0
    def enqueue(self, run_id, product, decision):
        self.rows.append((run_id, product, decision))
        return len(self.rows)
    def pending(self):
        return ({
            "id": 1, "store": "Mercado Livre", "title": "Produto",
            "current_price": 50, "previous_price": 100,
            "image_url": "https://image", "product_url": "https://product",
        },)


class FakeDelivery:
    destination = "5511999999999"
    def __init__(self): self.calls = 0
    def send(self, item):
        self.calls += 1
        return True, ""


def service_result(status):
    product = NormalizedProduct(
        "ml:1", "Mercado Livre", "Produto", current_price=50
    )
    decision = HunterDecision(
        product.deduplication_key, status, "motivo", 90,
        "excelente", "pipeline", ("kw",),
    )
    return HunterRunResult(
        "run", "success", (), 1, 1, (decision,), (product,),
        datetime.now(timezone.utc), datetime.now(timezone.utc),
    )


class FakeService:
    def __init__(self, result): self.result = result
    def run(self, sources): return self.result


def runner(status, delivery=None):
    return PromotionHunterRunner(
        FakeService(service_result(status)), FakeQueue(), FakeRepository(),
        DeliveryPolicy(), delivery,
        clock=lambda: datetime(2026, 7, 30, 23, tzinfo=timezone.utc),
    )


def test_only_approved_is_queued_and_analysis_only_never_sends():
    item = runner(DecisionStatus.APPROVED, FakeDelivery())
    result = item.run_once((), "analysis_only")
    # Em analysis_only, fila NÃO é persistida; queued=0, blocked=1
    assert result.queued == 0 and result.sent == 0
    assert result.blocked == 1
    assert item.delivery.calls == 0
    for status in (DecisionStatus.DISCARDED, DecisionStatus.PENDING):
        result = runner(status, FakeDelivery()).run_once((), "analysis_only")
        assert result.queued == 0 and result.sent == 0


def test_live_delivery_false_blocks_enqueue_and_delivery(monkeypatch):
    monkeypatch.delenv("PROMOTION_HUNTER_LIVE_DELIVERY", raising=False)
    item = runner(DecisionStatus.APPROVED, FakeDelivery())
    result = item.run_once((), "live")
    assert result.queued == 0 and result.sent == 0
    assert result.blocked == 1
    assert "live_delivery_desativado" in result.errors


def test_live_without_destination_blocks_enqueue():
    delivery = FakeDelivery()
    delivery.destination = ""
    item = runner(DecisionStatus.APPROVED, delivery)
    import os; os.environ["PROMOTION_HUNTER_LIVE_DELIVERY"] = "true"
    result = item.run_once((), "live")
    assert result.queued == 0 and result.sent == 0
    assert result.blocked == 1
    assert "destino_nao_configurado" in result.errors
    del os.environ["PROMOTION_HUNTER_LIVE_DELIVERY"]


def test_live_authorized_enqueues_and_delivers(monkeypatch):
    delivery = FakeDelivery()
    monkeypatch.setenv("PROMOTION_HUNTER_LIVE_DELIVERY", "true")
    item = PromotionHunterRunner(
        FakeService(service_result(DecisionStatus.APPROVED)), FakeQueue(),
        FakeRepository(),
        DeliveryPolicy(),
        delivery,
        clock=lambda: datetime(2026, 7, 30, 15, tzinfo=timezone.utc),
    )
    result = item.run_once((), "live")
    assert result.queued == 1 and result.sent == 1
    assert delivery.calls == 1


def test_max_messages_zero_blocks_enqueue(monkeypatch):
    delivery = FakeDelivery()
    monkeypatch.setenv("PROMOTION_HUNTER_LIVE_DELIVERY", "true")
    item = PromotionHunterRunner(
        FakeService(service_result(DecisionStatus.APPROVED)), FakeQueue(),
        FakeRepository(),
        DeliveryPolicy(max_products_per_keyword=5, max_messages_per_run=0),
        delivery,
        clock=lambda: datetime(2026, 7, 30, 23, tzinfo=timezone.utc),
    )
    result = item.run_once((), "live")
    assert result.queued == 0 and result.sent == 0
    assert result.blocked == 1
    assert "max_messages_zero" in result.errors


def test_concurrent_cycle_is_refused():
    item = runner(DecisionStatus.APPROVED)
    item.execution_lock.acquire()
    try:
        try:
            item.run_once(())
            raise AssertionError("deveria recusar")
        except RuntimeError:
            pass
    finally:
        item.execution_lock.release()


def test_runner_recovers_indeterminate_queue_and_can_restart():
    item = runner(DecisionStatus.APPROVED)
    assert item.queue.recovered == 1
    item.stop()
    assert item.stop_event.is_set()
    item.start()
    assert not item.stop_event.is_set()
