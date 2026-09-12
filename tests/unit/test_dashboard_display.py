from pathlib import Path

from busylib import types

from busybar_codex.busybar import BusyBarDisplay
from busybar_codex.dashboard import DisplayFrame
from busybar_codex.events import DisplayState
from busybar_codex.telemetry import Telemetry


class Client:
    def __init__(self) -> None:
        self.draws: list[types.DisplayElements] = []
        self.clears: list[str] = []
        self.uploads: list[str] = []

    def version(self) -> types.VersionInfo:
        return types.VersionInfo(api_semver="27.5.0")

    def assets_upload(self, application_name: str, filename: str, data: bytes) -> object:
        self.uploads.append(filename)
        return None

    def display_draw(self, display_data: types.DisplayElements) -> object:
        self.draws.append(display_data)
        return None

    def display_clear(self, *, application_name: str) -> object:
        self.clears.append(application_name)
        return None


def test_frame_renders_both_screens_and_actual_context_width(tmp_path: Path) -> None:
    client = Client()
    display = BusyBarDisplay(client, "test-app", 50, tmp_path, "http://device")
    frame = DisplayFrame(DisplayState.CODING, "#01", 2, 1, Telemetry("gpt-5.4", "high", 25, 200000))
    display.render_frame(frame)
    payload = client.draws[-1]
    assert {item.display for item in payload.elements} == {
        types.DisplayName.FRONT,
        types.DisplayName.BACK,
    }
    assert any(
        isinstance(item, types.TextElement) and "gpt-5.4" in item.text for item in payload.elements
    )
    front_label = next(item for item in payload.elements if item.id == "front-session")
    model_label = next(item for item in payload.elements if item.id == "front-state")
    assert isinstance(model_label, types.TextElement) and model_label.text == "GPT-5.4"
    back_label = next(item for item in payload.elements if item.id == "back-state")
    assert isinstance(front_label, types.TextElement) and front_label.text == "#01 RUN"
    assert isinstance(back_label, types.TextElement) and back_label.text == "CODING  #01"
    progress = next(item for item in payload.elements if item.id == "front-context-fill")
    assert isinstance(progress, types.RectangleElement)
    assert progress.width == 18
    assert progress.y == 15
    assert progress.height == 1
    for element in payload.elements:
        if element.id in {"front-context-track", "back-context-track", "back-context-fill"}:
            assert isinstance(element, types.RectangleElement)
            assert element.height == 1
            assert element.y == (15 if element.display == types.DisplayName.FRONT else 79)
    controls = next(item for item in payload.elements if item.id == "back-controls")
    assert isinstance(controls, types.TextElement)
    assert controls.text == ""
    uploads = list(client.uploads)
    display.render_frame(
        DisplayFrame(DisplayState.CODING, "#01", 2, 1, Telemetry("gpt-5.4", "high", 50, 200000))
    )
    assert client.uploads == uploads


def test_hide_clears_only_our_application(tmp_path: Path) -> None:
    client = Client()
    display = BusyBarDisplay(client, "test-app", 50, tmp_path, "http://device")
    display.render_frame(DisplayFrame(DisplayState.DONE, None, 0, 0, Telemetry(), hidden=True))
    assert client.clears == ["test-app"]
    assert client.draws == []


def test_unknown_context_has_no_filled_bar(tmp_path: Path) -> None:
    client = Client()
    display = BusyBarDisplay(client, "test-app", 50, tmp_path, "http://device")
    display.render_frame(DisplayFrame(DisplayState.DONE, None, 0, 0, Telemetry()))
    elements = client.draws[-1].elements
    fill = next(item for item in elements if item.id == "front-context-fill")
    assert isinstance(fill, types.RectangleElement)
    assert fill.fill_colors == ["#242424FF"]
    assert any(isinstance(item, types.TextElement) and "CTX N/A" in item.text for item in elements)


def test_missing_data_explicitly_hides_previous_elements(tmp_path: Path) -> None:
    client = Client()
    display = BusyBarDisplay(client, "test-app", 50, tmp_path, "http://device")
    display.render_frame(
        DisplayFrame(DisplayState.CODING, "a", 1, 0, Telemetry("gpt-5.4", "high", 50))
    )
    previous_ids = {element.id for element in client.draws[-1].elements}
    display.render_frame(DisplayFrame(DisplayState.DONE, "a", 1, 0, Telemetry()))
    elements = client.draws[-1].elements
    assert {element.id for element in elements} == previous_ids
    for element in elements:
        if isinstance(element, types.ImageElement):
            assert element.opacity == 0


def test_front_provider_icons_are_visible_for_both_model_families() -> None:
    from busybar_codex.rendering import frame_elements

    for model, provider in [("gpt-5.6-luna", "openai"), ("claude-opus-4-6", "anthropic")]:
        elements = frame_elements(
            DisplayFrame(DisplayState.QUESTION, "#02", 2, 1, Telemetry(model, "high"))
        )
        icon = next(item for item in elements if item.id == "front-provider")
        assert isinstance(icon, types.ImageElement)
        assert icon.opacity == 100 and icon.path == f"provider-{provider}.png"
        text = next(item for item in elements if item.id == "front-session")
        assert isinstance(text, types.TextElement) and text.text == "#02 ASK"


def test_effort_words_do_not_take_space_reserved_for_activity() -> None:
    from busybar_codex.rendering import frame_elements

    elements = frame_elements(
        DisplayFrame(DisplayState.CODING, "#01", 1, 0, Telemetry("gpt-5.6-sol", "high"))
    )
    front = next(item for item in elements if item.id == "front-session")
    back = next(item for item in elements if item.id == "back-effort")
    assert isinstance(front, types.TextElement) and front.text == "#01 RUN"
    assert isinstance(back, types.TextElement) and back.text == ""


def test_effort_scale_fills_bottom_three_of_five_single_pixels() -> None:
    from busybar_codex.rendering import frame_elements

    data = Telemetry(
        "gpt-example", "high", effort_levels=("low", "medium", "high", "xhigh", "ultra")
    )
    elements = frame_elements(DisplayFrame(DisplayState.CODING, "#01", 1, 0, data))
    pixels = [item for item in elements if item.id.startswith("front-effort-")]
    assert len(pixels) == 8
    visible = [
        item
        for item in pixels
        if isinstance(item, types.RectangleElement) and item.fill_colors != ["#000000FF"]
    ]
    assert len(visible) == 5
    assert all(
        isinstance(item, types.RectangleElement) and item.width == item.height == 1
        for item in pixels
    )
    assert [item.y for item in visible] == [13, 12, 11, 10, 9]
    assert all(item.x == 71 for item in visible)
    colors = [item.fill_colors for item in visible]
    assert colors == [["#2B7FFFFF"]] * 3 + [["#444444FF"]] * 2
    for item in elements:
        if item.id in {"front-state", "front-session"}:
            assert (
                isinstance(item, types.TextElement)
                and item.width is not None
                and item.x + item.width <= 70
            )


def test_effort_scale_tracks_actual_model_levels_and_hides_stale_pixels() -> None:
    from busybar_codex.rendering import frame_elements

    data = Telemetry(
        "gpt-example", "high", effort_levels=("low", "medium", "high", "xhigh", "max", "ultra")
    )
    previous = frame_elements(DisplayFrame(DisplayState.QUESTION, "#01", 1, 1, data))
    front = [item for item in previous if item.id.startswith("front-effort-")]
    assert (
        sum(
            isinstance(item, types.RectangleElement) and item.fill_colors != ["#000000FF"]
            for item in front
        )
        == 6
    )
    assert (
        sum(
            isinstance(item, types.RectangleElement) and item.fill_colors == ["#FFB000FF"]
            for item in front
        )
        == 3
    )
    missing = frame_elements(DisplayFrame(DisplayState.CODING, "#01", 1, 0, Telemetry()))
    assert {(item.id, type(item), item.display) for item in previous} == {
        (item.id, type(item), item.display) for item in missing
    }
    for item in missing:
        if "-effort-" in item.id:
            assert isinstance(item, types.RectangleElement)
            assert item.fill_colors == ["#000000FF"]
            assert "opacity" not in item.model_dump()


def test_activity_phase_labels_never_override_user_question_or_completion() -> None:
    from busybar_codex.dashboard import WorkActivity
    from busybar_codex.rendering import frame_elements

    for activity, word in [
        (WorkActivity.THINK, "THINK"),
        (WorkActivity.TOOL, "TOOL"),
        (WorkActivity.CHECK, "CHECK"),
        (WorkActivity.COMPACT, "COMPACT"),
    ]:
        for state, label in [
            (DisplayState.CODING, word),
            (DisplayState.QUESTION, "ASK"),
            (DisplayState.DONE, "DONE"),
        ]:
            frame = DisplayFrame(state, "#01", 1, 0, Telemetry(), activity=activity)
            front = next(item for item in frame_elements(frame) if item.id == "front-session")
            assert isinstance(front, types.TextElement) and front.text == "#01 " + label
