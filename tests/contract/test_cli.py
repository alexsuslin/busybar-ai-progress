import io
import json
from pathlib import Path

import pytest

from busybar_codex.cli import main
from busybar_codex.events import DisplayState
from busybar_codex.queue import EventQueue


def environment(tmp_path: Path) -> dict[str, str]:
    return {
        "BUSYBAR_CODEX_CONFIG_DIR": str(tmp_path / "config"),
        "BUSYBAR_CODEX_STATE_DIR": str(tmp_path / "state"),
        "BUSYBAR_CODEX_CACHE_DIR": str(tmp_path / "cache"),
        "BUSYBAR_CODEX_LOG_DIR": str(tmp_path / "logs"),
    }


def test_malformed_hook_input_fails_open_without_echoing_input(tmp_path: Path) -> None:
    private_input = "not-json-private-content"
    stdout = io.StringIO()
    stderr = io.StringIO()

    result = main(
        ["hook"],
        environ=environment(tmp_path),
        stdin=io.StringIO(private_input),
        stdout=stdout,
        stderr=stderr,
    )

    assert result == 0
    assert private_input not in stdout.getvalue()
    assert private_input not in stderr.getvalue()


def test_hook_writes_one_safe_event(tmp_path: Path) -> None:
    payload = {
        "hook_event_name": "UserPromptSubmit",
        "session_id": "s1",
        "prompt": "private prompt",
    }

    result = main(
        ["hook"],
        environ=environment(tmp_path),
        stdin=io.StringIO(json.dumps(payload)),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert result == 0
    events = EventQueue(tmp_path / "state" / "queue").drain()
    assert len(events) == 1
    assert events[0].state is DisplayState.CODING
    assert "private prompt" not in events[0].to_json()


def test_manual_set_queues_requested_state(tmp_path: Path) -> None:
    result = main(
        ["set", "question"],
        environ=environment(tmp_path),
        stdin=io.StringIO(),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert result == 0
    events = EventQueue(tmp_path / "state" / "queue").drain()
    assert [event.state for event in events] == [DisplayState.QUESTION]


def test_invalid_manual_state_returns_usage_error(tmp_path: Path) -> None:
    result = main(
        ["set", "unknown"],
        environ=environment(tmp_path),
        stdin=io.StringIO(),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert result == 2


class OnlineDisplay:
    def probe(self) -> str:
        return "25.0.0"


def test_doctor_reports_reachable_device(tmp_path: Path) -> None:
    stdout = io.StringIO()

    result = main(
        ["doctor"],
        environ=environment(tmp_path),
        stdin=io.StringIO(),
        stdout=stdout,
        stderr=io.StringIO(),
        display_factory=lambda _config: OnlineDisplay(),
    )

    assert result == 0
    assert "device: ok (API 25.0.0)" in stdout.getvalue()


def test_doctor_reports_redacted_address_and_hook_presence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hooks_dir = tmp_path / ".codex"
    hooks_dir.mkdir()
    (hooks_dir / "hooks.json").write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    values = environment(tmp_path)
    values["BUSYBAR_CODEX_ADDRESS"] = "http://user:private@127.0.0.1:8080"
    stdout = io.StringIO()

    result = main(
        ["doctor"],
        environ=values,
        stdin=io.StringIO(),
        stdout=stdout,
        stderr=io.StringIO(),
        display_factory=lambda _config: OnlineDisplay(),
    )

    report = stdout.getvalue()
    assert result == 0
    assert "address: http://127.0.0.1:8080" in report
    assert "hooks: ok" in report
    assert "private" not in report


def test_render_assets_writes_three_png_files(tmp_path: Path) -> None:
    output = tmp_path / "rendered"

    result = main(
        ["render-assets", "--output", str(output)],
        environ=environment(tmp_path),
        stdin=io.StringIO(),
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )

    assert result == 0
    assert sorted(path.name for path in output.glob("*.png")) == [
        "coding.png",
        "done.png",
        "question.png",
    ]
