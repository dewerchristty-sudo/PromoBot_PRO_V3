from datetime import datetime, timezone

from src.promotion_hunter.scheduler import PromotionHunterScheduler


class FakeTimer:
    instances = []
    def __init__(self, seconds, callback):
        self.seconds, self.callback, self.cancelled = seconds, callback, False
        self.daemon = False
        self.instances.append(self)
    def start(self): pass
    def cancel(self): self.cancelled = True


class FakePolicy:
    def __init__(self, allowed=True): self.allowed = allowed
    def within_window(self, now): return self.allowed


class FakeRunner:
    def __init__(self, allowed=True):
        self.calls = 0
        self.stopped = False
        self.started = False
        self.policy = FakePolicy(allowed)
    def run_once(self, sources, mode): self.calls += 1
    def stop(self): self.stopped = True
    def start(self): self.started = True


class FakeRepository:
    def __init__(self): self.states = []
    def update_scheduler_state(self, *args, **kwargs):
        self.states.append((args, kwargs))


def test_scheduler_has_one_timer_recurrence_and_safe_stop():
    FakeTimer.instances.clear()
    runner, repository = FakeRunner(), FakeRepository()
    scheduler = PromotionHunterScheduler(
        runner, (), repository, interval_minutes=30,
        clock=lambda: datetime(2026, 7, 30, tzinfo=timezone.utc),
        timer_factory=FakeTimer,
    )
    assert scheduler.start()
    assert runner.started
    assert not scheduler.start()
    assert len(FakeTimer.instances) == 1
    FakeTimer.instances[0].callback()
    assert runner.calls == 1
    assert FakeTimer.instances[-1].seconds == 1800
    scheduler.stop()
    assert runner.stopped and FakeTimer.instances[-1].cancelled


def test_scheduler_does_not_collect_outside_allowed_window():
    FakeTimer.instances.clear()
    runner, repository = FakeRunner(), FakeRepository()
    # Use a clock at 5 AM UTC = 2 AM BRT (outside 08-22 window)
    scheduler = PromotionHunterScheduler(
        runner, (), repository, timer_factory=FakeTimer,
        clock=lambda: datetime(2026, 7, 30, 5, 0, 0, tzinfo=timezone.utc),
    )
    scheduler.start()
    FakeTimer.instances[0].callback()
    assert runner.calls == 0
