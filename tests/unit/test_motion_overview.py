from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path

import pytest
from busylib import types

from busybar_codex.busybar import BusyBarDisplay, DisplayUnavailableError
from busybar_codex.config import Config
from busybar_codex.daemon import StatusDaemon
from busybar_codex.dashboard import DisplayFrame
from busybar_codex.events import DisplayState, SafeEvent
from busybar_codex.queue import EventQueue
from busybar_codex.rendering import frame_elements
from busybar_codex.state import SessionReducer
from busybar_codex.telemetry import Telemetry


class Clock:
    seconds = 0.0

    def wall(self) -> datetime:
        return datetime(2026, 9, 12, tzinfo=UTC) + timedelta(seconds=self.seconds)

    def monotonic(self) -> float:
        return self.seconds


class Client:
    def __init__(self) -> None:
        self.draws: list[types.DisplayElements] = []
        self.clears: list[str] = []

    def version(self) -> types.VersionInfo:
        return types.VersionInfo(api_semver="27.5.0")

    def assets_upload(self, application_name: str, filename: str, data: bytes) -> object:
        return None

    def display_draw(self, display_data: types.DisplayElements) -> object:
        self.draws.append(display_data)
        return None

    def display_clear(self, *, application_name: str) -> object:
        self.clears.append(application_name)
        return None

    def render(self, state: DisplayState) -> None:
        raise AssertionError("dashboard expected")


def daemon_for(
    path: Path, *, enabled: bool = True
) -> tuple[StatusDaemon, Clock, list[DisplayFrame]]:
    clock = Clock()
    frames: list[DisplayFrame] = []
    daemon = StatusDaemon(
        EventQueue(path / "queue"),
        SessionReducer(86400),
        Client(),
        path / "state.json",
        clock=clock.wall,
        animation_clock=clock.monotonic,
        animations=enabled,
        frame_renderer=frames.append,
        jitter=lambda: 0.0,
    )
    return daemon, clock, frames


def emit(daemon: StatusDaemon, clock: Clock, state: DisplayState, session: str = "a") -> None:
    reason = (
        "prompt"
        if state is DisplayState.CODING
        else "stop"
        if state is DisplayState.DONE
        else "user_input"
    )
    daemon.queue.put(SafeEvent(session, None, state, clock.wall().isoformat(), reason))
    daemon.step()


def test_motion_is_throttled_and_question_is_not_delayed(tmp_path: Path) -> None:
    daemon, clock, frames = daemon_for(tmp_path)
    emit(daemon, clock, DisplayState.CODING)
    assert frames[-1].motion_phase == 0
    clock.seconds = 0.49
    daemon.step()
    assert len(frames) == 1
    clock.seconds = 0.5
    daemon.step()
    assert len(frames) == 2 and frames[-1].motion_phase == 1
    assert not frames[-1].full_refresh
    clock.seconds = 0.51
    emit(daemon, clock, DisplayState.QUESTION)
    assert len(frames) == 3 and frames[-1].state is DisplayState.QUESTION
    assert frames[-1].motion_phase == 0
    label = next(item for item in frame_elements(frames[-1]) if item.id == "front-session")
    assert isinstance(label, types.TextElement) and label.text == "#01 ASK"


def test_motion_does_not_starve_full_refresh_or_continue_while_hidden(tmp_path: Path) -> None:
    daemon, clock, frames = daemon_for(tmp_path)
    emit(daemon, clock, DisplayState.CODING)
    for tick in range(1, 21):
        clock.seconds = tick / 2
        daemon.step()
    assert frames[-1].full_refresh
    assert sum(frame.full_refresh for frame in frames) == 2
    daemon.dashboard.hidden = True
    daemon.step()
    assert frames[-1].hidden and frames[-1].motion_phase is None
    count = len(frames)
    clock.seconds += 30
    daemon.step()
    assert len(frames) == count


def test_static_mode_keeps_status_and_ten_second_refresh(tmp_path: Path) -> None:
    daemon, clock, frames = daemon_for(tmp_path, enabled=False)
    emit(daemon, clock, DisplayState.CODING)
    for tick in range(1, 20):
        clock.seconds = tick / 2
        daemon.step()
    assert len(frames) == 1 and frames[-1].motion_phase is None
    clock.seconds = 10
    daemon.step()
    assert len(frames) == 2 and frames[-1].full_refresh


def test_done_acknowledgement_is_brief_and_not_replayed_on_show(tmp_path: Path) -> None:
    daemon, clock, frames = daemon_for(tmp_path)
    emit(daemon, clock, DisplayState.DONE)
    assert frames[-1].motion_phase is None
    clock.seconds = 1
    emit(daemon, clock, DisplayState.CODING)
    clock.seconds = 2
    emit(daemon, clock, DisplayState.DONE)
    assert frames[-1].motion_phase == 0
    clock.seconds = 4
    daemon.step()
    assert frames[-1].motion_phase is None
    daemon.dashboard.hidden = True
    daemon.step()
    daemon.dashboard.hidden = False
    daemon.step()
    assert frames[-1].motion_phase is None


def test_motion_cannot_bypass_transport_backoff(tmp_path: Path) -> None:
    daemon, clock, frames = daemon_for(tmp_path)
    attempts: list[float] = []

    def render(frame: DisplayFrame) -> None:
        attempts.append(clock.seconds)
        if len(attempts) < 3:
            raise DisplayUnavailableError("synthetic")
        frames.append(frame)

    daemon.frame_renderer = render
    emit(daemon, clock, DisplayState.CODING)
    for tick in range(1, 7):
        clock.seconds = tick / 2
        daemon.step()
    assert attempts == [0, 1, 3]
    assert frames[-1].motion_phase == 6


def test_motion_only_payload_preserves_text_scrolling_and_full_refresh(tmp_path: Path) -> None:
    client = Client()
    display = BusyBarDisplay(client, "synthetic", 50, tmp_path, "http://device")
    frame = DisplayFrame(DisplayState.CODING, "#01", 1, 0, Telemetry(), motion_phase=0)
    display.render_frame(frame)
    from dataclasses import replace

    display.render_frame(replace(frame, motion_phase=1))
    assert {item.id for item in client.draws[-1].elements} == {"front-motion", "back-motion"}
    display.render_frame(replace(frame, motion_phase=2, full_refresh=True))
    assert any(item.id == "front-state" for item in client.draws[-1].elements)
    display.render_frame(replace(frame, motion_phase=None))
    assert all(
        isinstance(item, types.RectangleElement) and item.fill_colors == ["#000000FF"]
        for item in client.draws[-1].elements
    )
    display.render_frame(replace(frame, hidden=True))
    display.render_frame(replace(frame, motion_phase=3))
    assert any(item.id == "front-state" for item in client.draws[-1].elements)


def test_motion_stays_separate_from_context_and_hides_with_stable_ids() -> None:
    signatures: list[set[tuple[str, str, str]]] = []
    for state in (DisplayState.CODING, DisplayState.QUESTION, DisplayState.DONE):
        for phase in (None, 0, 1, 2, 3, 7):
            elements = frame_elements(
                DisplayFrame(state, "#01", 1, 0, Telemetry(), motion_phase=phase)
            )
            signatures.append(
                {(item.id, type(item).__name__, str(item.display)) for item in elements}
            )
            motion = next(item for item in elements if item.id == "front-motion")
            assert isinstance(motion, types.RectangleElement)
            assert motion.x >= 0 and motion.x + motion.width <= 12
            assert motion.y == 13 and motion.height == 1
            if phase is None:
                assert motion.fill_colors == ["#000000FF"]
    assert all(signature == signatures[0] for signature in signatures)


def test_overview_pages_follow_selection_and_exclude_dismissed_sessions(tmp_path: Path) -> None:
    daemon, clock, frames = daemon_for(tmp_path, enabled=False)
    for number in range(1, 11):
        emit(daemon, clock, DisplayState.CODING, f"s{number}")
    daemon.dashboard.move(8, daemon.reducer)
    daemon.step()
    frame = frames[-1]
    assert frame.session_tag == "#09"
    assert [item.number for item in frame.overview.sessions] == [9, 10]
    assert (frame.overview.page, frame.overview.pages) == (2, 2)
    elements = frame_elements(frame)
    selected = next(item for item in elements if item.id == "back-overview-selected-0")
    assert isinstance(selected, types.RectangleElement) and selected.fill_colors == ["#FFFFFFFF"]
    daemon.dashboard.dismiss("s9", daemon.reducer)
    daemon.step()
    assert frames[-1].session_count == 9
    assert all(item.number != 9 for item in frames[-1].overview.sessions)
    for number in range(2, 11):
        daemon.reducer.dismiss(f"s{number}")
    daemon.step()
    assert not frames[-1].overview.sessions
    cleared = frame_elements(frames[-1])
    assert {(item.id, type(item), item.display) for item in cleared} == {
        (item.id, type(item), item.display) for item in elements
    }
    assert all(
        item.text == ""
        for item in cleared
        if isinstance(item, types.TextElement) and item.id.startswith("back-overview-")
    )


@pytest.mark.parametrize("value", ["0", "false", "FALSE"])
def test_motion_environment_can_disable_default(tmp_path: Path, value: str) -> None:
    assert Config.load(path=tmp_path / "missing", environ={}).animations
    assert not Config.load(
        path=tmp_path / "missing", environ={"BUSYBAR_CODEX_ANIMATIONS": value}
    ).animations


@pytest.mark.parametrize("value", ["yes", "2", "", "NaN"])
def test_invalid_motion_setting_is_rejected(tmp_path: Path, value: str) -> None:
    with pytest.raises(ValueError, match="animations"):
        Config.load(path=tmp_path / "missing", environ={"BUSYBAR_CODEX_ANIMATIONS": value})


def test_irregular_polling_never_sends_motion_less_than_half_second_apart(tmp_path: Path) -> None:
    daemon, clock, frames = daemon_for(tmp_path)
    emit(daemon, clock, DisplayState.CODING)
    sent = [0.0]
    for instant in (0.6, 1.0, 1.2, 1.6, 1.8, 2.0, 2.4):
        before = len(frames)
        clock.seconds = instant
        daemon.step()
        if len(frames) != before:
            sent.append(instant)
    assert len(sent) >= 3
    assert all(later - earlier >= 0.5 for earlier, later in pairwise(sent))


def test_transport_recovery_restores_scene_after_failed_motion(tmp_path: Path) -> None:
    from dataclasses import replace

    from busylib import exceptions

    class InterruptedClient(Client):
        failing = False

        def display_draw(self, display_data: types.DisplayElements) -> object:
            if self.failing:
                raise exceptions.BusyBarRequestError("synthetic")
            return super().display_draw(display_data)

    client = InterruptedClient()
    display = BusyBarDisplay(client, "synthetic", 50, tmp_path, "http://device")
    frame = DisplayFrame(DisplayState.CODING, "#01", 1, 0, Telemetry(), motion_phase=0)
    display.render_frame(frame)
    client.failing = True
    with pytest.raises(DisplayUnavailableError):
        display.render_frame(replace(frame, motion_phase=1))
    client.failing = False
    display.render_frame(replace(frame, motion_phase=2))
    assert any(item.id == "front-state" for item in client.draws[-1].elements)


@pytest.mark.parametrize("value", ["true", "false"])
def test_toml_motion_setting_and_environment_override(tmp_path: Path, value: str) -> None:
    path = tmp_path / "config.toml"
    path.write_text(f"animations = {value}\n")
    assert Config.load(path=path, environ={}).animations is (value == "true")
    assert Config.load(path=path, environ={"BUSYBAR_CODEX_ANIMATIONS": "1"}).animations


@pytest.mark.parametrize("value", ['"false"', "0", "[]"])
def test_toml_motion_requires_boolean(tmp_path: Path, value: str) -> None:
    path = tmp_path / "config.toml"
    path.write_text(f"animations = {value}\n")
    with pytest.raises(ValueError, match="animations"):
        Config.load(path=path, environ={})


def test_cli_no_animation_renders_static_scene(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import io

    from busybar_codex.cli import main

    client = Client()
    reducer = SessionReducer(86400)
    reducer.apply(
        SafeEvent("synthetic", None, DisplayState.CODING, datetime.now(UTC).isoformat(), "prompt")
    )
    reducer.save(tmp_path / "state" / "sessions.json")

    def once(self: StatusDaemon) -> None:
        self.step()

    def factory(config: Config) -> BusyBarDisplay:
        return BusyBarDisplay(
            client, config.application_name, config.priority, tmp_path, config.base_url
        )

    monkeypatch.setattr(StatusDaemon, "run", once)
    env = {
        f"BUSYBAR_CODEX_{kind.upper()}_DIR": str(tmp_path / kind)
        for kind in ("config", "state", "cache", "log")
    }
    assert (
        main(
            ["run", "--no-input", "--no-telemetry", "--no-animation"],
            environ=env,
            stdout=io.StringIO(),
            display_factory=factory,
        )
        == 0
    )
    motion = next(item for item in client.draws[0].elements if item.id == "front-motion")
    assert isinstance(motion, types.RectangleElement) and motion.fill_colors == ["#000000FF"]
