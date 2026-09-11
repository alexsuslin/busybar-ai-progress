from __future__ import annotations

from importlib.resources import files
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .events import DisplayState

WIDTH = 72
HEIGHT = 16
FONT = ImageFont.load_default(size=10)
STYLES = {
    DisplayState.CODING: ("CODING...", "#2B7FFF"),
    DisplayState.QUESTION: ("QUESTION?", "#FFB000"),
    DisplayState.DONE: ("DONE", "#36D17C"),
}


def render_assets(output_dir: Path) -> dict[DisplayState, Path]:
    """Render the three front-display images with deterministic settings."""

    output_dir.mkdir(parents=True, exist_ok=True)
    rendered: dict[DisplayState, Path] = {}
    for state, (label, color) in STYLES.items():
        image = Image.new("RGB", (WIDTH, HEIGHT), "black")
        draw = ImageDraw.Draw(image)
        bounds = draw.textbbox((0, 0), label, font=FONT)
        text_width = bounds[2] - bounds[0]
        text_height = bounds[3] - bounds[1]
        x = (WIDTH - text_width) // 2
        y = (HEIGHT - text_height) // 2 - bounds[1]
        draw.rectangle((1, 5, 2, 10), fill=color)
        draw.rectangle((69, 5, 70, 10), fill=color)
        draw.text((x, y), label, font=FONT, fill=color)
        path = output_dir / f"{state.value}.png"
        image.save(path, format="PNG", optimize=False, compress_level=9)
        rendered[state] = path
    return rendered


def bundled_asset(state: DisplayState) -> Path:
    if state not in STYLES:
        raise ValueError(f"no display asset for state: {state}")
    return Path(str(files("busybar_codex").joinpath("assets", f"{state.value}.png")))
