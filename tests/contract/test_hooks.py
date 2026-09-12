import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from busybar_codex.events import DisplayState, normalize_hook
from busybar_codex.install import install_hooks
from busybar_codex.queue import EventQueue

PROJECT_ROOT = Path(__file__).parents[2]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell contract")
def test_all_windows_hook_commands_run_inside_codex_powershell(tmp_path: Path) -> None:
    hooks_path = tmp_path / "hooks.json"
    install_hooks("codex", hooks_path, tmp_path / "state")
    hooks = json.loads(hooks_path.read_text(encoding="utf-8"))
    hook_handlers = [
        hook
        for hook_groups in hooks["hooks"].values()
        for hook_group in hook_groups
        for hook in hook_group["hooks"]
    ]
    configured_types = {hook["type"] for hook in hook_handlers}
    commands = {hook["commandWindows"] for hook in hook_handlers}
    configured_timeouts = {hook["timeout"] for hook in hook_handlers}
    assert configured_types == {"command"}
    assert len(commands) == 1
    assert configured_timeouts == {3}
    command = commands.pop()
    hook_timeout = configured_timeouts.pop()
    payload = json.dumps(
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "windows-hook-contract",
        }
    )
    environ = os.environ.copy()
    environ.update(
        {
            "BUSYBAR_CODEX_CONFIG_DIR": str(tmp_path / "config"),
            "BUSYBAR_CODEX_STATE_DIR": str(tmp_path / "state"),
            "BUSYBAR_CODEX_CACHE_DIR": str(tmp_path / "cache"),
            "BUSYBAR_CODEX_LOG_DIR": str(tmp_path / "logs"),
        }
    )

    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        cwd=PROJECT_ROOT / "tests" / "contract",
        env=environ,
        input=payload,
        capture_output=True,
        text=True,
        timeout=hook_timeout,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    events = EventQueue(tmp_path / "state" / "queue").drain()
    assert [event.state for event in events] == [DisplayState.CODING]


def test_codex_request_user_input_shape_is_reduced_without_arguments() -> None:
    private_question = "Should production be overwritten?"
    payload = {
        "session_id": "thr_123",
        "transcript_path": "D:/private/rollout.jsonl",
        "cwd": "D:/private/project",
        "permission_mode": "default",
        "hook_event_name": "PreToolUse",
        "tool_name": "request_user_input",
        "tool_input": {"questions": [{"question": private_question}]},
    }

    event = normalize_hook(payload, datetime(2026, 9, 11, tzinfo=UTC))

    assert event is not None
    assert event.session_id == "thr_123"
    assert event.state is DisplayState.QUESTION
    assert private_question not in event.to_json()
    assert "rollout.jsonl" not in event.to_json()
