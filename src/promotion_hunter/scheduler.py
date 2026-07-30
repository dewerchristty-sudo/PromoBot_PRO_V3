from __future__ import annotations

import threading
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .config import (
    ALLOWED_START_HOUR,
    ALLOWED_END_HOUR,
    INTERVAL_MINUTES,
    OPERATIONAL_TIMEZONE,
)


class PromotionHunterScheduler:
    def __init__(self, runner, sources, repository, interval=None,
                 interval_minutes=None, mode="analysis_only",
                 clock=None, timer_factory=None):
        self.runner = runner
        self.sources = sources
        self.repository = repository
        _minutes = int(interval_minutes or interval or INTERVAL_MINUTES)
        self.interval_seconds = max(_minutes, 1) * 60
        self.mode = mode
        self.running = False
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._timer_factory = timer_factory or threading.Timer
        self._timer = None
        self.lock = threading.Lock()

    def start(self):
        if not self.lock.acquire(blocking=False):
            return False
        self.running = True
        self.runner.start()
        self._schedule_next()
        return True

    def stop(self):
        self.running = False
        if self._timer:
            self._timer.cancel()
            self._timer = None
        self.runner.stop()
        self.repository.update_scheduler_state(False)
        try:
            self.lock.release()
        except RuntimeError:
            pass

    def _within_operational_window(self):
        now = self._clock().astimezone(OPERATIONAL_TIMEZONE)
        return ALLOWED_START_HOUR <= now.hour < ALLOWED_END_HOUR

    def _tick(self):
        if not self.running:
            return
        if self._within_operational_window():
            self.runner.run_once(self.sources, self.mode)
        self._schedule_next()

    def _schedule_next(self):
        if not self.running:
            return
        self._timer = self._timer_factory(self.interval_seconds, self._tick)
        self._timer.daemon = True
        self._timer.start()