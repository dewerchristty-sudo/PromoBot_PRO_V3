from datetime import datetime, timedelta, timezone

import pytest

from src.promotion_hunter.delivery import DeliveryPolicy, DeliveryResult
from src.promotion_hunter.delivery.retry_classification import (
    DeliveryFailureKind,
)
from src.promotion_hunter.runner import PromotionHunterRunner


class FakeClock:
    def __init__(self):
        self.value = datetime(2026, 8, 1, 15, tzinfo=timezone.utc)
        self.calls = []

    def __call__(self):
        self.calls.append(self.value)
        return self.value

    def advance(self, seconds):
        self.value += timedelta(seconds=seconds)


class FakeRepository:
    def __init__(self, clock):
        self.clock = clock
        self.last_sent = None
        self.attempts = []
        self.in_transaction = False

    def sent_count_since(self, _since):
        return sum(status == "sent" for _, status in self.attempts)

    def last_sent_at(self):
        return self.last_sent

    def start_attempt(self, identifier, _started):
        assert not self.in_transaction
        return identifier

    def finish_attempt(
        self, identifier, _attempt_id, status, finished, _error, _permanent
    ):
        self.attempts.append((identifier, status))
        if status == "sent":
            self.last_sent = finished


class FakeQueue:
    def __init__(self, count):
        self.count = count
        self.pending_calls = []

    def recover(self):
        return 0

    def pending(self, limit=100, after=None):
        self.pending_calls.append((limit, after))
        after_id = int(after[1]) if after else 0
        return tuple(
            {
                "id": number, "store": "Amazon", "title": f"Item {number}",
                "current_price": 10, "previous_price": 20,
                "image_url": "https://example.test/image.jpg",
                "product_url": "https://example.test/product",
                "approved_at": f"2026-08-01T15:{number // 60:02d}:{number % 60:02d}+00:00",
            }
            for number in range(after_id + 1, self.count + 1)
        )[:limit]


class FakeDelivery:
    destination = "5511999999999"

    def __init__(self, results=()):
        self.results = iter(results)
        self.calls = []

    def send(self, item):
        self.calls.append(item["id"])
        return next(self.results, DeliveryResult(True))


def make_runner(count, *, results=(), waiter=None, policy=None):
    clock = FakeClock()
    repository = FakeRepository(clock)
    waits = []

    def advancing_waiter(seconds):
        assert repository.in_transaction is False
        waits.append(seconds)
        clock.advance(seconds)
        return False

    runner = PromotionHunterRunner(
        service=None,
        queue=FakeQueue(count),
        repository=repository,
        policy=policy or DeliveryPolicy(
            max_messages_per_run=10,
            minimum_interval_seconds=3,
        ),
        delivery=FakeDelivery(results),
        clock=clock,
        waiter=waiter or advancing_waiter,
    )
    return runner, clock, repository, waits


def test_accelerated_processes_ten_sequentially(monkeypatch):
    monkeypatch.setenv("PROMOTION_HUNTER_LIVE_DELIVERY", "true")
    runner, clock, _repository, waits = make_runner(12)

    sent, blocked, errors = runner._deliver_pending()

    assert sent == 10
    assert runner.delivery.calls == list(range(1, 11))
    assert waits == [3.0] * 9
    assert len(set(clock.calls)) >= 10
    assert errors == ["limite_execucao"]
    assert blocked == 1


def test_short_and_empty_queues_do_not_wait_unnecessarily(monkeypatch):
    monkeypatch.setenv("PROMOTION_HUNTER_LIVE_DELIVERY", "true")
    short, _clock, _repository, waits = make_runner(3)
    assert short._deliver_pending()[0] == 3
    assert waits == [3.0, 3.0]

    empty, _clock, _repository, empty_waits = make_runner(0)
    assert empty._deliver_pending() == (0, 0, [])
    assert empty_waits == []


def test_stop_during_wait_interrupts_sequence(monkeypatch):
    monkeypatch.setenv("PROMOTION_HUNTER_LIVE_DELIVERY", "true")
    holder = {}

    def stopping_waiter(_seconds):
        holder["runner"].stop()
        return True

    runner, _clock, _repository, _waits = make_runner(
        5, waiter=stopping_waiter
    )
    holder["runner"] = runner

    assert runner._deliver_pending()[0] == 1
    assert runner.delivery.calls == [1]


def test_permanent_failure_does_not_block_next_and_temporary_is_retryable(
    monkeypatch,
):
    monkeypatch.setenv("PROMOTION_HUNTER_LIVE_DELIVERY", "true")
    results = (
        DeliveryResult(
            False, "imagem permanente", DeliveryFailureKind.PERMANENT
        ),
        DeliveryResult(False, "timeout", DeliveryFailureKind.TEMPORARY),
        DeliveryResult(True),
    )
    runner, _clock, repository, waits = make_runner(3, results=results)

    sent, _blocked, errors = runner._deliver_pending()

    assert sent == 1
    assert runner.delivery.calls == [1, 2, 3]
    assert [status for _, status in repository.attempts] == [
        "failed", "failed", "sent"
    ]
    assert "imagem permanente" in errors and "timeout" in errors
    assert waits == []


def test_normal_mode_waits_remaining_interval_and_continues(monkeypatch):
    monkeypatch.setenv("PROMOTION_HUNTER_LIVE_DELIVERY", "true")
    policy = DeliveryPolicy(
        max_messages_per_run=3,
        max_messages_per_hour=20,
        max_messages_per_session=20,
        minimum_interval_seconds=600,
    )
    runner, _clock, _repository, waits = make_runner(2, policy=policy)

    sent, blocked, errors = runner._deliver_pending()

    assert sent == 2 and blocked == 0
    assert errors == []
    assert waits == [600.0]


@pytest.mark.parametrize("count", [20, 100, 127, 300])
def test_consumes_all_eligible_items_across_batches(monkeypatch, count):
    monkeypatch.setenv("PROMOTION_HUNTER_LIVE_DELIVERY", "true")
    policy = DeliveryPolicy(
        max_messages_per_run=count + 1,
        max_messages_per_hour=count + 1,
        max_messages_per_session=count + 1,
        minimum_interval_seconds=0,
    )
    runner, _clock, repository, waits = make_runner(count, policy=policy)

    sent, blocked, errors = runner._deliver_pending()

    assert sent == count
    assert blocked == 0 and errors == [] and waits == []
    assert runner.delivery.calls == list(range(1, count + 1))
    assert len(runner.delivery.calls) == len(set(runner.delivery.calls))
    assert len(repository.attempts) == count
    expected_data_pages = (count + 99) // 100
    assert len(runner.queue.pending_calls) == expected_data_pages + 1


def test_hour_limit_stops_immediately_without_reading_later_batches(monkeypatch):
    monkeypatch.setenv("PROMOTION_HUNTER_LIVE_DELIVERY", "true")
    policy = DeliveryPolicy(
        max_messages_per_run=300,
        max_messages_per_hour=2,
        max_messages_per_session=300,
        minimum_interval_seconds=0,
    )
    runner, _clock, _repository, _waits = make_runner(300, policy=policy)

    assert runner._deliver_pending() == (2, 1, ["limite_hora"])
    assert runner.delivery.calls == [1, 2]
    assert len(runner.queue.pending_calls) == 1
