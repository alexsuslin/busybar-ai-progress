from datetime import UTC, datetime, timedelta
from pathlib import Path

from busybar_codex.busybar import DisplayUnavailableError
from busybar_codex.daemon import StatusDaemon
from busybar_codex.events import DisplayState, SafeEvent
from busybar_codex.queue import EventQueue
from busybar_codex.state import SessionReducer


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 9, 11, 12, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class RecordingDisplay:
    def __init__(self, failures: int = 0) -> None:
        self.failures = failures
        self.states: list[DisplayState] = []

    def render(self, state: DisplayState) -> None:
        self.states.append(state)
        if self.failures:
            self.failures -= 1
            raise DisplayUnavailableError("offline")


def queue_event(queue: EventQueue, clock: Clock, state: DisplayState) -> None:
    queue.put(
        SafeEvent(
            session_id="s1",
            turn_id="t1",
            state=state,
            timestamp=clock().isoformat(),
            reason="test",
        )
    )


def make_daemon(
    tmp_path: Path,
    display: RecordingDisplay,
    clock: Clock,
) -> tuple[StatusDaemon, EventQueue]:
    queue = EventQueue(tmp_path / "queue")
    daemon = StatusDaemon(
        queue=queue,
        reducer=SessionReducer(stale_after_seconds=86_400),
        display=display,
        snapshot_path=tmp_path / "state.json",
        clock=clock,
        jitter=lambda: 0.0,
    )
    return daemon, queue


def test_daemon_renders_only_aggregate_changes(tmp_path: Path) -> None:
    clock = Clock()
    display = RecordingDisplay()
    daemon, queue = make_daemon(tmp_path, display, clock)
    queue_event(queue, clock, DisplayState.CODING)
    daemon.step()
    queue_event(queue, clock, DisplayState.CODING)
    daemon.step()

    assert display.states == [DisplayState.CODING]


def test_failed_render_obeys_backoff(tmp_path: Path) -> None:
    clock = Clock()
    display = RecordingDisplay(failures=2)
    daemon, queue = make_daemon(tmp_path, display, clock)
    queue_event(queue, clock, DisplayState.CODING)

    daemon.step()
    clock.advance(0.9)
    daemon.step()
    clock.advance(0.1)
    daemon.step()

    assert display.states == [DisplayState.CODING, DisplayState.CODING]


def test_new_state_replaces_failed_pending_state_immediately(tmp_path: Path) -> None:
    clock = Clock()
    display = RecordingDisplay(failures=1)
    daemon, queue = make_daemon(tmp_path, display, clock)
    queue_event(queue, clock, DisplayState.CODING)
    daemon.step()
    queue_event(queue, clock, DisplayState.QUESTION)

    daemon.step()

    assert display.states == [DisplayState.CODING, DisplayState.QUESTION]


def test_processed_state_is_saved_before_display_recovers(tmp_path: Path) -> None:
    clock = Clock()
    display = RecordingDisplay(failures=1)
    daemon, queue = make_daemon(tmp_path, display, clock)
    queue_event(queue, clock, DisplayState.QUESTION)

    assert daemon.step() is DisplayState.QUESTION

    restored = SessionReducer.load(tmp_path / "state.json", stale_after_seconds=86_400)
    assert restored.aggregate(clock()) is DisplayState.QUESTION
