import json
import os
from dataclasses import replace
from pathlib import Path
from urllib.request import Request, urlopen

import pytest

from busybar_codex.busybar import BusyBarDisplay, DisplayBusyError
from busybar_codex.config import Config
from busybar_codex.events import DisplayState

pytestmark = pytest.mark.emulator


def emulator_url() -> str:
    value = os.environ.get("BUSYBAR_EMULATOR_URL")
    if value is None:
        pytest.skip("BUSYBAR_EMULATOR_URL is not set")
    return value.rstrip("/")


def post_scenario(base_url: str, path: str, payload: dict[str, object]) -> None:
    request = Request(
        f"{base_url}{path}",
        data=json.dumps(payload).encode(),
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=2) as response:
        assert response.status == 200


def test_all_states_render_on_emulator(tmp_path: Path) -> None:
    config = replace(
        Config.load(environ={"BUSYBAR_CODEX_ADDRESS": emulator_url()}),
        cache_dir=tmp_path,
    )
    display = BusyBarDisplay.from_config(config)

    assert display.probe()
    display.ensure_assets()
    for state in (DisplayState.CODING, DisplayState.QUESTION, DisplayState.DONE):
        display.render(state)


def test_emulator_priority_conflict_is_classified(tmp_path: Path) -> None:
    base_url = emulator_url()
    config = replace(
        Config.load(environ={"BUSYBAR_CODEX_ADDRESS": base_url}),
        cache_dir=tmp_path,
    )
    display = BusyBarDisplay.from_config(config)
    try:
        post_scenario(base_url, "/api/_scenario/steal", {"priority": 99, "duration_ms": 5000})
        with pytest.raises(DisplayBusyError):
            display.render(DisplayState.CODING)
    finally:
        post_scenario(base_url, "/api/_scenario/reset", {})
