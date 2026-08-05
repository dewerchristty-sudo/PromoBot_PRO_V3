from __future__ import annotations

import threading
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .config import (
    ALLOWED_START_HOUR,
    ALLOWED_END_HOUR,
    INTERVAL_MINUTES,
    OPERATIONAL_TIMEZONE,
)


logger = logging.getLogger(__name__)


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
        self._tick_lock = threading.Lock()

    def start(self):
        if not self.lock.acquire(blocking=False):
            return False
        self.running = True
        self.runner.start()
        now = self._clock()
        try:
            self.repository.update_scheduler_state(
                True,
                last_run_at=None,
                next_run_at=(
                    now + timedelta(seconds=self.interval_seconds)
                ).isoformat(),
                last_error="",
            )
            self._schedule_next()
            return True
        except Exception:
            self.running = False
            self.runner.stop()
            self.lock.release()
            raise

    def stop(self):
        self.running = False
        if self._timer:
            self._timer.cancel()
            self._timer = None
        try:
            self.runner.stop()
            self.repository.update_scheduler_state(False)
        finally:
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
        if not self._tick_lock.acquire(blocking=False):
            return
        self._timer = None
        started_at = self._clock()
        last_error = ""
        try:
            self.repository.update_scheduler_state(
                True,
                last_run_at=started_at.isoformat(),
                next_run_at=None,
                last_error="",
            )
            if self._within_operational_window():
                self.runner.run_once(self.sources, self.mode)
        except Exception as exc:
            last_error = " ".join(str(exc).split())[:300]
            logger.exception("Promotion Hunter: falha no ciclo agendado")
        finally:
            try:
                if self.running:
                    next_run_at = (
                        self._clock()
                        + timedelta(seconds=self.interval_seconds)
                    ).isoformat()
                    try:
                        self.repository.update_scheduler_state(
                            True,
                            last_run_at=started_at.isoformat(),
                            next_run_at=next_run_at,
                            last_error=last_error,
                        )
                    except Exception:
                        logger.exception(
                            "Promotion Hunter: falha ao persistir heartbeat"
                        )
                    finally:
                        if self.running:
                            self._schedule_next()
            finally:
                self._tick_lock.release()

    def _schedule_next(self):
        if not self.running:
            return
        if self._timer is not None:
            self._timer.cancel()
        self._timer = self._timer_factory(self.interval_seconds, self._tick)
        self._timer.daemon = True
        self._timer.start()
