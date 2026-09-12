from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from busybar_codex.busybar import DisplayUnavailableError
from busybar_codex.daemon import StatusDaemon
from busybar_codex.dashboard import DisplayFrame
from busybar_codex.events import DisplayState, SafeEvent
from busybar_codex.queue import EventQueue
from busybar_codex.state import SessionReducer
from busybar_codex.telemetry import Telemetry


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
            reason="prompt",
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
        animations=False,
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


def test_dashboard_refreshes_metadata_but_keeps_hidden(tmp_path: Path) -> None:
    clock = Clock()
    frames: list[DisplayFrame] = []
    commands: list[str | int] = []
    data = Telemetry("gpt-5.4", "high", 25, 200000)

    def drain() -> list[str | int]:
        result = list(commands)
        commands.clear()
        return result

    daemon = StatusDaemon(
        EventQueue(tmp_path / "queue"),
        SessionReducer(86400),
        RecordingDisplay(),
        tmp_path / "state.json",
        clock=clock,
        frame_renderer=frames.append,
        telemetry=lambda _id: data,
        controls=drain,
    )
    queue_event(daemon.queue, clock, DisplayState.CODING)
    daemon.step()
    data = Telemetry("gpt-5.4", "high", 50, 200000)
    clock.advance(2)
    daemon.step()
    assert frames[-1].telemetry.context_percent == 50
    commands.append("hide")
    daemon.step()
    assert frames[-1].hidden
    count = len(frames)
    queue_event(daemon.queue, clock, DisplayState.QUESTION)
    clock.advance(20)
    daemon.step()
    assert len(frames) == count
    commands.append("show")
    daemon.step()
    assert not frames[-1].hidden
    assert frames[-1].state is DisplayState.QUESTION


def test_dismissal_is_saved_before_clear_and_new_event_restores_card(tmp_path: Path) -> None:
    clock = Clock()
    frames: list[DisplayFrame] = []
    commands: list[str | int] = []
    snapshot = tmp_path / "state.json"

    def drain() -> list[str | int]:
        result = list(commands)
        commands.clear()
        return result

    def render(frame: DisplayFrame) -> None:
        if frame.hidden:
            restored = SessionReducer.load(snapshot, 86400)
            from busybar_codex.dashboard import Dashboard

            assert Dashboard().select(restored) is None
        frames.append(frame)

    daemon = StatusDaemon(
        EventQueue(tmp_path / "queue"),
        SessionReducer(86400),
        RecordingDisplay(),
        snapshot,
        clock=clock,
        frame_renderer=render,
        controls=drain,
    )
    queue_event(daemon.queue, clock, DisplayState.CODING)
    daemon.step()
    commands.append("dismiss")
    daemon.step()
    assert frames[-1].hidden
    count = len(frames)
    clock.advance(20)
    daemon.step()
    assert len(frames) == count
    queue_event(daemon.queue, clock, DisplayState.QUESTION)
    daemon.step()
    assert not frames[-1].hidden
    assert frames[-1].session_tag == "#01"
    assert frames[-1].question_count == 1


def test_dismissed_cards_are_excluded_from_screen_counts(tmp_path: Path) -> None:
    clock = Clock()
    frames: list[DisplayFrame] = []
    daemon, queue = make_daemon(tmp_path, RecordingDisplay(), clock)
    daemon.frame_renderer = frames.append
    queue_event(queue, clock, DisplayState.QUESTION)
    queue.put(SafeEvent("s2", None, DisplayState.CODING, clock().isoformat(), "prompt"))
    daemon.step()
    daemon.controls = lambda: ["dismiss"]
    daemon.step()
    assert frames[-1].session_tag == "#02"
    assert frames[-1].session_count == 1
    assert frames[-1].question_count == 0
    assert daemon.reducer.records["s1"].state is DisplayState.QUESTION


def test_start_closes_displayed_card_when_new_question_arrives_in_same_poll(tmp_path: Path) -> None:
    clock = Clock()
    frames: list[DisplayFrame] = []
    daemon, queue = make_daemon(tmp_path, RecordingDisplay(), clock)
    daemon.frame_renderer = frames.append
    queue_event(queue, clock, DisplayState.CODING)
    daemon.step()
    queue.put(SafeEvent("s2", None, DisplayState.QUESTION, clock().isoformat(), "user_input"))
    daemon.controls = lambda: ["dismiss"]
    daemon.step()
    assert frames[-1].session_tag == "#02"
    assert frames[-1].state is DisplayState.QUESTION
    assert frames[-1].session_count == 1
    assert set(daemon.reducer.dismissed) == {"s1"}


def test_start_closes_last_successful_frame_after_a_render_failure(tmp_path: Path) -> None:
    clock = Clock()
    frames: list[DisplayFrame] = []
    daemon, queue = make_daemon(tmp_path, RecordingDisplay(), clock)
    daemon.frame_renderer = frames.append
    queue_event(queue, clock, DisplayState.CODING)
    daemon.step()

    def offline(_frame: DisplayFrame) -> None:
        raise DisplayUnavailableError("offline")

    daemon.frame_renderer = offline
    queue.put(SafeEvent("s2", None, DisplayState.QUESTION, clock().isoformat(), "user_input"))
    daemon.step()
    daemon.controls = lambda: ["dismiss"]
    daemon.step()
    assert set(daemon.reducer.dismissed) == {"s1"}
    daemon.controls = lambda: []
    daemon.frame_renderer = frames.append
    clock.advance(2)
    daemon.step()
    assert frames[-1].session_tag == "#02"


def test_failed_dismissal_save_is_retried_before_clearing_screen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = Clock()
    frames: list[DisplayFrame] = []
    daemon, queue = make_daemon(tmp_path, RecordingDisplay(), clock)
    daemon.frame_renderer = frames.append
    queue_event(queue, clock, DisplayState.CODING)
    daemon.step()
    save = daemon.reducer.save
    failed = False

    def transient_failure(path: Path) -> None:
        nonlocal failed
        if not failed:
            failed = True
            raise OSError("synthetic write failure")
        save(path)

    monkeypatch.setattr(daemon.reducer, "save", transient_failure)
    daemon.controls = lambda: ["dismiss"]
    with pytest.raises(OSError):
        daemon.step()
    assert not frames[-1].hidden
    daemon.controls = lambda: []
    daemon.step()
    assert frames[-1].hidden
    restored = SessionReducer.load(tmp_path / "state.json", 86400)
    assert not restored.visible_records


def test_rollout_completion_recovers_missing_hook_and_does_not_reopen_dismissal(
    tmp_path: Path,
) -> None:
    clock = Clock()
    frames: list[DisplayFrame] = []
    daemon, queue = make_daemon(tmp_path, RecordingDisplay(), clock)
    daemon.frame_renderer = frames.append
    queue_event(queue, clock, DisplayState.CODING)
    daemon.step()
    clock.advance(1)
    # Real hooks can use a continuation ID unlike the root rollout turn ID.
    complete = SafeEvent(
        "s1", "root-turn", DisplayState.DONE, clock().isoformat(), "rollout_complete"
    )
    daemon.lifecycle = lambda _id: (complete,)
    assert daemon.step() is DisplayState.DONE
    assert frames[-1].state is DisplayState.DONE
    daemon.controls = lambda: ["dismiss"]
    daemon.step()
    daemon.controls = lambda: []
    daemon.step()
    assert frames[-1].hidden
    assert (
        SessionReducer.load(tmp_path / "state.json", 86400).records["s1"].state is DisplayState.DONE
    )


def test_old_rollout_start_does_not_override_newer_question_and_future_is_ignored(
    tmp_path: Path,
) -> None:
    clock = Clock()
    daemon, queue = make_daemon(tmp_path, RecordingDisplay(), clock)
    old = SafeEvent("s1", "t1", DisplayState.CODING, clock().isoformat(), "rollout_started")
    clock.advance(1)
    queue_event(queue, clock, DisplayState.QUESTION)
    daemon.lifecycle = lambda _id: (old,)
    assert daemon.step() is DisplayState.QUESTION
    future = SafeEvent(
        "s1", "t1", DisplayState.DONE, (clock() + timedelta(days=1)).isoformat(), "rollout_complete"
    )
    daemon.lifecycle = lambda _id: (future,)
    assert daemon.step() is DisplayState.QUESTION


def test_rollout_completion_preserves_final_question_but_next_turn_finishes(tmp_path: Path) -> None:
    clock = Clock()
    daemon, queue = make_daemon(tmp_path, RecordingDisplay(), clock)
    started = SafeEvent("s1", "t1", DisplayState.CODING, clock().isoformat(), "rollout_started")
    clock.advance(1)
    queue.put(SafeEvent("s1", "t1", DisplayState.QUESTION, clock().isoformat(), "final_question"))
    clock.advance(1)
    complete = SafeEvent("s1", "t1", DisplayState.DONE, clock().isoformat(), "rollout_complete")
    daemon.lifecycle = lambda _id: (started, complete)
    assert daemon.step() is DisplayState.QUESTION
    clock.advance(1)
    started = SafeEvent("s1", "t2", DisplayState.CODING, clock().isoformat(), "rollout_started")
    clock.advance(1)
    complete = SafeEvent("s1", "t2", DisplayState.DONE, clock().isoformat(), "rollout_complete")
    assert daemon.step() is DisplayState.DONE


def test_prompt_frame_shows_thinking_phase_without_changing_lifecycle(tmp_path: Path) -> None:
    from busylib import types

    from busybar_codex.rendering import frame_elements

    clock = Clock()
    frames: list[DisplayFrame] = []
    daemon, queue = make_daemon(tmp_path, RecordingDisplay(), clock)
    daemon.frame_renderer = frames.append
    queue_event(queue, clock, DisplayState.CODING)
    daemon.step()
    front = next(item for item in frame_elements(frames[-1]) if item.id == "front-session")
    assert isinstance(front, types.TextElement) and front.text == "#01 THINK"
    assert frames[-1].state is DisplayState.CODING
    assert frames[-1].question_count == 0


def test_normalized_tools_render_activity_and_preserve_explicit_wait(tmp_path: Path) -> None:
    from busylib import types

    from busybar_codex.events import normalize_hook
    from busybar_codex.rendering import frame_elements

    clock = Clock()
    frames: list[DisplayFrame] = []
    daemon, queue = make_daemon(tmp_path, RecordingDisplay(), clock)
    daemon.frame_renderer = frames.append
    sequence = [
        ("UserPromptSubmit", None, "THINK"),
        ("PreToolUse", "Bash", "TOOL"),
        ("PermissionRequest", "Bash", "CHECK"),
        ("PostToolUse", "Bash", "THINK"),
        ("PreCompact", None, "COMPACT"),
        ("PostCompact", None, "THINK"),
        ("PreToolUse", "request_user_input", "ASK"),
        ("PostToolUse", "Bash", "ASK"),
        ("PostToolUse", "request_user_input", "THINK"),
        ("Stop", None, "DONE"),
    ]
    for hook, tool, expected in sequence:
        event = normalize_hook(
            {"hook_event_name": hook, "session_id": "s1", "turn_id": "t1", "tool_name": tool},
            clock(),
        )
        assert event is not None
        queue.put(event)
        daemon.step()
        front = next(item for item in frame_elements(frames[-1]) if item.id == "front-session")
        assert isinstance(front, types.TextElement) and front.text == f"#01 {expected}"
        assert frames[-1].question_count == (1 if expected == "ASK" else 0)
        clock.advance(1)


def test_freshness_and_reset_update_on_existing_refresh_without_new_events(tmp_path: Path) -> None:
    from busylib import types

    from busybar_codex.rendering import frame_elements
    from busybar_codex.telemetry import RateWindow

    clock = Clock()
    frames: list[DisplayFrame] = []
    daemon, queue = make_daemon(tmp_path, RecordingDisplay(), clock)
    daemon.frame_renderer = frames.append
    data = Telemetry(
        context_percent=85,
        limits=(RateWindow(50, 300, clock().timestamp() + 20),),
        usage_observed_at=clock().timestamp() - 895,
    )
    daemon.telemetry = lambda _id: data
    queue_event(queue, clock, DisplayState.CODING)
    daemon.step()

    def freshness() -> str:
        row = next(item for item in frame_elements(frames[-1]) if item.id == "back-freshness")
        assert isinstance(row, types.TextElement)
        return row.text

    assert freshness() == "DATA 14m"
    clock.advance(5)
    daemon.step()
    assert len(frames) == 1
    clock.advance(5)
    daemon.step()
    assert len(frames) == 2 and freshness() == "STALE 15m"
    clock.advance(10)
    daemon.step()
    assert frames[-1].telemetry.limits == ()
    assert frames[-1].state is DisplayState.CODING
    daemon.dashboard.hidden = True
    daemon.step()
    count = len(frames)
    clock.advance(120)
    daemon.step()
    assert len(frames) == count
