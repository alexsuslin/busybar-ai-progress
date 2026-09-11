import hashlib
from pathlib import Path

from PIL import Image

from busybar_codex.assets import bundled_asset, render_assets
from busybar_codex.events import DisplayState

EXPECTED_COLORS = {
    DisplayState.CODING: (43, 127, 255),
    DisplayState.QUESTION: (255, 176, 0),
    DisplayState.DONE: (54, 209, 124),
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_assets_are_rgb_72_by_16_with_state_color(tmp_path: Path) -> None:
    paths = render_assets(tmp_path)

    assert set(paths) == {
        DisplayState.CODING,
        DisplayState.QUESTION,
        DisplayState.DONE,
    }
    for state, path in paths.items():
        with Image.open(path) as image:
            assert image.size == (72, 16)
            assert image.mode == "RGB"
            assert EXPECTED_COLORS[state] in set(image.get_flattened_data())


def test_each_state_has_distinct_artwork(tmp_path: Path) -> None:
    paths = render_assets(tmp_path)

    assert len({digest(path) for path in paths.values()}) == 3


def test_rendering_is_byte_deterministic(tmp_path: Path) -> None:
    first = render_assets(tmp_path / "first")
    second = render_assets(tmp_path / "second")

    assert {state: digest(path) for state, path in first.items()} == {
        state: digest(path) for state, path in second.items()
    }


def test_bundled_asset_points_to_generated_package_file() -> None:
    for state in (DisplayState.CODING, DisplayState.QUESTION, DisplayState.DONE):
        path = bundled_asset(state)
        assert path.name == f"{state.value}.png"
        assert path.is_file()
