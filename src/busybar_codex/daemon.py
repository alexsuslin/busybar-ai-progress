from __future__ import annotations

import logging
import random
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from typing import Protocol

from .busybar import DisplayBusyError, DisplayUnavailableError
from .dashboard import Dashboard, DisplayFrame
from .events import DisplayState, SafeEvent
from .queue import EventQueue
from .state import SessionReducer
from .telemetry import Telemetry

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
        frame_renderer: Callable[[DisplayFrame], None] | None = None,
        telemetry: Callable[[str], Telemetry] | None = None,
        controls: Callable[[], list[str | int]] | None = None,
        lifecycle: Callable[[str], tuple[SafeEvent, ...]] | None = None,
    ) -> None:
        self.queue = queue
        self.reducer = reducer
        self.display = display
        self.snapshot_path = snapshot_path
        self.poll_interval_seconds = poll_interval_seconds
        self.clock = clock or (lambda: datetime.now(UTC))
        self.jitter = jitter or (lambda: random.uniform(0.0, 0.25))
        self.dashboard = Dashboard()
        self.lifecycle: Callable[[str], tuple[SafeEvent, ...]] = lifecycle or (lambda _id: ())
        self.frame_renderer = frame_renderer
        self.telemetry: Callable[[str], Telemetry] = telemetry or (lambda _id: Telemetry())
        self.controls: Callable[[], list[str | int]] = controls or (lambda: [])
        self._displayed_session_id: str | None = None
        self._snapshot_dirty = False
        self._last_frame: DisplayFrame | None = None
        self._pending_frame: DisplayFrame | None = None
        self._last_frame_at: datetime | None = None
        self._last_rendered: DisplayState | None = None
        self._pending_state: DisplayState | None = None
        self._next_attempt_at: datetime | None = None
        self._attempts = 0

    def step(self) -> DisplayState:
        now = self.clock()
        before = dict(self.reducer.records)
        dismissed_before = dict(self.reducer.dismissed)
        events = self.queue.drain()
        for event in events:
            self.reducer.apply(event)
        # Reconcile tracked sessions only. Marker timestamps prevent an old
        # start/completion from overwriting a newer hook or reopening a dismissal.
        for session_id in list(self.reducer.records):
            for marker in self.lifecycle(session_id):
                record = self.reducer.records.get(session_id)
                if (
                    record is not None
                    and marker.session_id == session_id
                    and datetime.fromisoformat(record.timestamp)
                    < datetime.fromisoformat(marker.timestamp)
                    <= now
                    and not (
                        marker.reason == "rollout_complete" and record.reason == "final_question"
                    )
                ):
                    self.reducer.apply(marker)
        state = self.reducer.aggregate(now)
        if self.frame_renderer is not None:
            for action in self.controls():
                if action == "dismiss":
                    # Input refers to the card the device actually received, not a
                    # new automatic selection or a frame still waiting for retry.
                    if self._displayed_session_id is not None:
                        self.dashboard.dismiss(self._displayed_session_id, self.reducer)
                else:
                    self.dashboard.action(action, self.reducer)
        if events or before != self.reducer.records or dismissed_before != self.reducer.dismissed:
            self._snapshot_dirty = True
        if self._snapshot_dirty:
            self.reducer.save(self.snapshot_path)
            self._snapshot_dirty = False

        if self.frame_renderer is not None:
            self._render_dashboard(now, state)
            return state

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
            delay = min(2 ** min(self._attempts, 5), 30) + self.jitter()
            self._attempts += 1
            self._next_attempt_at = now + timedelta(seconds=delay)
            logger.warning("display retry scheduled state=%s error=%s", state, type(error).__name__)
        else:
            self._last_rendered = state
            self._next_attempt_at = None
            self._attempts = 0
        return state

    def _render_dashboard(self, now: datetime, aggregate: DisplayState) -> None:
        assert self.frame_renderer is not None
        record = self.dashboard.select(self.reducer)
        data = self.telemetry(record.session_id) if record else Telemetry()
        data = replace(data, limits=data.current_limits(now.timestamp()))
        frame = DisplayFrame(
            record.state if record else aggregate,
            self.reducer.session_label(record.session_id) if record else None,
            len(self.reducer.visible_records),
            sum(r.state is DisplayState.QUESTION for r in self.reducer.visible_records.values()),
            data,
            self.dashboard.hidden or record is None,
        )
        if frame.hidden:
            frame = DisplayFrame(DisplayState.DONE, None, 0, 0, Telemetry(), hidden=True)
        if frame != self._pending_frame:
            self._pending_frame = frame
            # Visibility changes are immediate; telemetry changes cannot bypass backoff.
            if self._last_frame is not None and frame.hidden != self._last_frame.hidden:
                self._next_attempt_at = None
        refresh = not frame.hidden and (
            self._last_frame_at is None or (now - self._last_frame_at).total_seconds() >= 10
        )
        if frame == self._last_frame and not refresh:
            return
        if self._next_attempt_at is not None and now < self._next_attempt_at:
            return
        try:
            self.frame_renderer(frame)
        except (DisplayBusyError, DisplayUnavailableError) as error:
            delay = min(2 ** min(self._attempts, 5), 30) + self.jitter()
            self._attempts += 1
            self._next_attempt_at = now + timedelta(seconds=delay)
            logger.warning("display retry scheduled error=%s", type(error).__name__)
        else:
            self._displayed_session_id = record.session_id if record and not frame.hidden else None
            self._last_frame = frame
            self._last_frame_at = now
            self._next_attempt_at = None
            self._attempts = 0

    def run(self, stop_event: Event | None = None) -> None:
        stop = stop_event or Event()
        while not stop.is_set():
            try:
                self.step()
            except Exception as error:
                logger.error("daemon step failed error=%s", type(error).__name__)
            stop.wait(self.poll_interval_seconds)
