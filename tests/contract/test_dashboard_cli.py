import io
import json
from pathlib import Path

import pytest

from busybar_codex.cli import main
from busybar_codex.local import ControlInbox, InstanceLock, MetadataStore
from busybar_codex.telemetry import Telemetry


def environment(path: Path) -> dict[str, str]:
    return {
        f"BUSYBAR_CODEX_{name.upper()}_DIR": str(path / name)
        for name in ("config", "state", "cache", "log")
    }


def test_claude_statusline_writes_only_metadata_without_lifecycle(tmp_path: Path) -> None:
    payload = {
        "session_id": "claude-a",
        "model": {"id": "claude-opus-4-6"},
        "effort": {"level": "high"},
        "context_window": {"used_percentage": 12},
        "prompt": "PRIVATE",
        "cwd": "PRIVATE",
    }
    stdout = io.StringIO()
    assert (
        main(
            ["claude-statusline"],
            environ=environment(tmp_path),
            stdin=io.StringIO(json.dumps(payload)),
            stdout=stdout,
        )
        == 0
    )
    value = MetadataStore(tmp_path / "state" / "metadata").read("claude-a")
    assert value.model == "claude-opus-4-6"
    assert value.context_percent == 12
    assert not list((tmp_path / "state" / "queue").glob("*.json"))
    assert "PRIVATE" not in stdout.getvalue()
    for path in (tmp_path / "state").rglob("*.json"):
        assert "PRIVATE" not in path.read_text()


def test_hide_enqueues_control_without_touching_device(tmp_path: Path) -> None:
    assert main(["hide"], environ=environment(tmp_path), stdout=io.StringIO()) == 0
    assert ControlInbox(tmp_path / "state" / "controls").drain() == ["hide"]


def test_bad_config_cannot_block_hook(tmp_path: Path) -> None:
    env = environment(tmp_path)
    env["BUSYBAR_CODEX_PRIORITY"] = "wrong"
    stderr = io.StringIO()
    assert main(["hook"], environ=env, stdin=io.StringIO("PRIVATE"), stderr=stderr) == 0
    assert stderr.getvalue() == ""


def test_metadata_roundtrip_and_corrupt_file_fail_soft(tmp_path: Path) -> None:
    store = MetadataStore(tmp_path)
    data = Telemetry("claude-sonnet-4-6", "high", 0)
    store.write("a", data)
    assert store.read("a") == data
    assert store.read("b") == Telemetry()
    next(tmp_path.glob("*.json")).write_text("broken")
    assert store.read("a") == Telemetry()


def test_second_daemon_cannot_take_same_state_directory(tmp_path: Path) -> None:
    import pytest

    with (
        InstanceLock(tmp_path / "daemon.lock"),
        pytest.raises(OSError),
        InstanceLock(tmp_path / "daemon.lock"),
    ):
        raise AssertionError("second daemon was allowed")
    with InstanceLock(tmp_path / "daemon.lock"):
        pass


def test_session_start_model_hint_survives_without_statusline(tmp_path: Path) -> None:
    payload = {
        "session_id": "native-claude",
        "hook_event_name": "SessionStart",
        "model": "claude-sonnet-4-6",
        "prompt": "PRIVATE",
    }
    assert (
        main(["hook"], environ=environment(tmp_path), stdin=io.StringIO(json.dumps(payload))) == 0
    )
    data = MetadataStore(tmp_path / "state" / "hints").read("native-claude")
    assert data.model == "claude-sonnet-4-6"
    assert data.context_percent is None


def test_metadata_source_searches_all_configured_codex_roots(tmp_path: Path) -> None:
    from busybar_codex.cli import telemetry_source
    from busybar_codex.config import Config

    first, second = tmp_path / "windows", tmp_path / "linux"
    second.mkdir()
    (second / "rollout-a.jsonl").write_text(
        json.dumps({"type": "turn_context", "payload": {"model": "gpt-5.4", "effort": "high"}})
        + "\n"
    )
    source = telemetry_source(Config(state_dir=tmp_path / "state"), [first, second])
    assert source("a").model == "gpt-5.4"


def test_duplicate_run_explains_existing_instance_without_contacting_device(tmp_path: Path) -> None:
    import pytest

    stderr = io.StringIO()
    with InstanceLock(tmp_path / "state" / "daemon.lock"):
        result = main(
            ["run"],
            environ=environment(tmp_path),
            stdout=io.StringIO(),
            stderr=stderr,
            display_factory=lambda _config: pytest.fail("duplicate run must not contact device"),
        )
    assert result == 1
    assert "already running" in stderr.getvalue()
    assert "Ctrl+C" in stderr.getvalue()
    assert "OSError" not in stderr.getvalue()


def test_dismiss_enqueues_local_control_without_touching_device(tmp_path: Path) -> None:
    assert main(["dismiss"], environ=environment(tmp_path), stdout=io.StringIO()) == 0
    assert ControlInbox(tmp_path / "state" / "controls").drain() == ["dismiss"]


def test_status_distinguishes_closed_cards_from_visible_sessions(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    from busybar_codex.events import DisplayState, SafeEvent
    from busybar_codex.state import SessionReducer

    class Probe:
        def probe(self) -> str:
            return "27.5.0"

    reducer = SessionReducer(86400)
    reducer.apply(
        SafeEvent("synthetic.a", None, DisplayState.DONE, datetime.now(UTC).isoformat(), "stop")
    )
    reducer.dismiss("synthetic.a")
    reducer.save(tmp_path / "state" / "sessions.json")
    stdout = io.StringIO()
    assert (
        main(
            ["status"],
            environ=environment(tmp_path),
            stdout=stdout,
            display_factory=lambda _: Probe(),
        )
        == 0
    )
    sessions = json.loads(stdout.getvalue())["sessions"]
    assert sessions[0]["id"] == "#01"
    assert sessions[0]["dismissed"] is True


def test_lifecycle_source_uses_configured_rollouts_and_refreshes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from busybar_codex.cli import lifecycle_source
    from busybar_codex.config import Config
    from busybar_codex.events import DisplayState

    clock = [1.0]
    monkeypatch.setattr("busybar_codex.cli.time.monotonic", lambda: clock[0])
    source_dir = tmp_path / "rollouts"
    source_dir.mkdir()
    path = source_dir / "rollout-a.jsonl"
    path.write_text(
        json.dumps(
            {
                "type": "event_msg",
                "timestamp": "2026-09-12T06:30:00Z",
                "payload": {"type": "task_started", "turn_id": "t1"},
            }
        )
        + "\n"
    )
    source = lifecycle_source(Config(state_dir=tmp_path / "state"), [source_dir])
    assert source("a")[-1].state is DisplayState.CODING
    with path.open("a") as stream:
        stream.write(
            json.dumps(
                {
                    "type": "event_msg",
                    "timestamp": "2026-09-12T06:46:00Z",
                    "payload": {"type": "task_complete", "turn_id": "t1"},
                }
            )
            + "\n"
        )
    clock[0] += 2
    assert source("a")[-1].state is DisplayState.DONE
    assert source("missing") == ()
