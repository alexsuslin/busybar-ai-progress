import os
import time
from dataclasses import replace
from pathlib import Path

import pytest
from busylib import BusyBar, types
from PIL import Image

from busybar_codex.busybar import BusyBarDisplay
from busybar_codex.config import Config
from busybar_codex.dashboard import DisplayFrame
from busybar_codex.events import DisplayState
from busybar_codex.telemetry import Telemetry


@pytest.mark.hardware
@pytest.mark.skipif(
    os.environ.get("BUSYBAR_HARDWARE_TEST") != "1", reason="opt-in real display test"
)
def test_real_device_clears_old_progress_when_metadata_disappears(tmp_path: Path) -> None:
    config = replace(Config.load(), application_name="codex-dashboard-test", cache_dir=tmp_path)
    client = BusyBar(config.base_url, token=config.token, timeout=2, max_retries=0)
    display = BusyBarDisplay(
        client, config.application_name, config.priority, tmp_path, config.base_url
    )
    try:
        # Simulate the previous release's persistent hint before the new frame.
        client.display_draw(
            types.DisplayElements(
                application_name=config.application_name,
                priority=config.priority,
                elements=[
                    types.TextElement(
                        id="back-controls",
                        text="START: HIDE/SHOW   DIAL: SESSION",
                        x=0,
                        y=69,
                        width=160,
                        font="tiny",
                        display=types.DisplayName.BACK,
                    )
                ],
            )
        )
        display.render_frame(
            DisplayFrame(DisplayState.CODING, "#01", 2, 0, Telemetry("gpt-5.4", "high", 50, 200000))
        )
        time.sleep(0.2)
        first = Image.frombytes("RGB", (72, 16), client.screen("front"))
        assert first.getpixel((20, 15)) != first.getpixel((60, 15))
        assert first.getpixel((5, 14)) == (0, 0, 0)
        back = Image.frombytes("RGB", (160, 80), client.screen("back"))
        # The firmware owns the status/battery strip at x >= 144.
        assert back.crop((0, 69, 144, 79)).getbbox() is None
        assert back.getpixel((20, 79)) != back.getpixel((100, 79))
        display.render_frame(DisplayFrame(DisplayState.DONE, "#01", 2, 0, Telemetry()))
        time.sleep(0.2)
        second = Image.frombytes("RGB", (72, 16), client.screen("front"))
        assert second.getpixel((20, 15)) == second.getpixel((60, 15))
        assert second.getpixel((5, 5)) == (0, 0, 0)
    finally:
        try:
            display.render_frame(
                DisplayFrame(DisplayState.DONE, None, 0, 0, Telemetry(), hidden=True)
            )
        finally:
            client.close()


@pytest.mark.hardware
@pytest.mark.skipif(
    os.environ.get("BUSYBAR_HARDWARE_TEST") != "1", reason="opt-in real display test"
)
def test_real_device_recovers_done_from_synthetic_rollout_without_stop(tmp_path: Path) -> None:
    import json
    from datetime import UTC, datetime, timedelta

    from busybar_codex.daemon import StatusDaemon
    from busybar_codex.events import SafeEvent
    from busybar_codex.queue import EventQueue
    from busybar_codex.state import SessionReducer
    from busybar_codex.telemetry import CodexTelemetry

    config = replace(Config.load(), application_name="codex-dashboard-test", cache_dir=tmp_path)
    display = BusyBarDisplay.from_config(config)
    source = CodexTelemetry(tmp_path)
    started = datetime.now(UTC) - timedelta(seconds=2)
    queue = EventQueue(tmp_path / "queue")
    queue.put(SafeEvent("probe", "hook-turn", DisplayState.CODING, started.isoformat(), "prompt"))
    daemon = StatusDaemon(
        queue,
        SessionReducer(86400),
        display,
        tmp_path / "state.json",
        frame_renderer=display.render_frame,
        lifecycle=source.read_lifecycle,
    )
    try:
        assert daemon.step() is DisplayState.CODING
        (tmp_path / "rollout-probe.jsonl").write_text(
            json.dumps(
                {
                    "type": "event_msg",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "payload": {"type": "task_complete", "turn_id": "root-turn"},
                }
            )
            + "\n"
        )
        assert daemon.step() is DisplayState.DONE
        time.sleep(0.2)
        client = BusyBar(config.base_url, token=config.token, timeout=2, max_retries=0)
        try:
            picture = Image.frombytes("RGB", (72, 16), client.screen("front"))
        finally:
            client.close()
        pixels = picture.crop((14, 0, 72, 14)).tobytes()
        assert any(
            pixels[i + 1] > pixels[i] and pixels[i + 1] > pixels[i + 2]
            for i in range(0, len(pixels), 3)
        )
    finally:
        try:
            display.render_frame(
                DisplayFrame(DisplayState.DONE, None, 0, 0, Telemetry(), hidden=True)
            )
        finally:
            display.close()
