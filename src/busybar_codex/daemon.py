from __future__ import annotations

import logging
import random
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from typing import Protocol

from .busybar import DisplayBusyError, DisplayUnavailableError
from .events import DisplayState
from .queue import EventQueue
from .state import SessionReducer

logger = logging.getLogger(__name__)


class StateDisplay(Protocol):
    def render(self, state: DisplayState) -> None: ...


class StatusDaemon:
    """Drain hook events, persist state, and render aggregate changes."""

    def __init__(
        self,
        queue: EventQueue,
        reducer: SessionReducer,
        display: StateDisplay,
        snapshot_path: Path,
        *,
        poll_interval_seconds: float = 0.2,
        clock: Callable[[], datetime] | None = None,
        jitter: Callable[[], float] | None = None,
    ) -> None:
        self.queue = queue
        self.reducer = reducer
        self.display = display
        self.snapshot_path = snapshot_path
        self.poll_interval_seconds = poll_interval_seconds
        self.clock = clock or (lambda: datetime.now(UTC))
        self.jitter = jitter or (lambda: random.uniform(0.0, 0.25))
        self._last_rendered: DisplayState | None = None
        self._pending_state: DisplayState | None = None
        self._next_attempt_at: datetime | None = None
        self._attempts = 0

    def step(self) -> DisplayState:
        now = self.clock()
        before = dict(self.reducer.records)
        events = self.queue.drain()
        for event in events:
            self.reducer.apply(event)
        state = self.reducer.aggregate(now)
        if events or before != self.reducer.records:
            self.reducer.save(self.snapshot_path)

        if state != self._pending_state:
            self._pending_state = state
            self._next_attempt_at = None
            self._attempts = 0
        if state == self._last_rendered:
            return state
        if self._next_attempt_at is not None and now < self._next_attempt_at:
            return state

        try:
            self.display.render(state)
        except (DisplayBusyError, DisplayUnavailableError) as error:
            delay = min(2**self._attempts, 30) + self.jitter()
            self._attempts += 1
            self._next_attempt_at = now + timedelta(seconds=delay)
            logger.warning("display retry scheduled state=%s error=%s", state, type(error).__name__)
        else:
            self._last_rendered = state
            self._next_attempt_at = None
            self._attempts = 0
        return state

    def run(self, stop_event: Event | None = None) -> None:
        stop = stop_event or Event()
        while not stop.is_set():
            try:
                self.step()
            except Exception as error:
                logger.exception("daemon step failed error=%s", type(error).__name__)
            stop.wait(self.poll_interval_seconds)
