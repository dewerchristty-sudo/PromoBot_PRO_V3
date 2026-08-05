import sys
from types import SimpleNamespace

from src.promotion_hunter.official_runtime import (
    OfficialHunterController,
    build_sources,
)


class FakeLock:
    def __init__(self): self.released = False
    def acquire(self): return True
    def release(self): self.released = True


class FakeScheduler:
    def __init__(self, runner, sources, repository, interval, mode):
        self.running = False
        self.mode = mode
    def start(self): self.running = True; return True
    def stop(self): self.running = False


class Closable:
    def __init__(self): self.closed = False; self.stopped = False
    def close(self): self.closed = True
    def stop(self): self.stopped = True


def test_frozen_runtime_starts_in_process_and_stops_cleanly(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    repository, pipeline, runner = Closable(), Closable(), Closable()
    calls = []
    def factory(**kwargs):
        calls.append(kwargs)
        return repository, pipeline, runner, ()
    lock = FakeLock()
    controller = OfficialHunterController(
        runtime_factory=factory,
        scheduler_factory=FakeScheduler,
        process_lock_factory=lambda: lock,
    )
    assert controller.start(mode="analysis_only")
    assert controller.running
    assert calls == [{
        "mode": "analysis_only", "limit": 5,
        "max_messages": 3, "per_store": 6, "stores": None,
        "max_session_messages": 10,
    }]
    controller.stop()
    assert not controller.running
    assert runner.stopped and pipeline.closed and repository.closed
    assert lock.released


def test_catalog_contains_only_authorized_profile_sources():
    rotating = build_sources(limit=5, per_store=100)
    sources = list(rotating)
    assert len(sources) == 240
    assert {item.configuration["profile_id"] for item in sources} == {
        "tecnologia_acessorios", "cosmeticos", "eletrodomesticos"
    }
