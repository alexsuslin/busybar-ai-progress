import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from busybar_codex.cli import main
from busybar_codex.install import install_hooks, uninstall_hooks
from busybar_codex.queue import EventQueue


def test_install_merges_idempotently_and_uninstall_preserves_user_settings(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    original = {
        "permissions": {"allow": ["Read"]},
        "statusLine": {"type": "command", "command": "my-status"},
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "my-hook"}]}]},
    }
    path.write_text(json.dumps(original))
    install_hooks("claude", path, tmp_path / "state")
    first = json.loads(path.read_text())
    install_hooks("claude", path, tmp_path / "state")
    assert json.loads(path.read_text()) == first
    assert first["statusLine"] == original["statusLine"]
    assert first["hooks"]["Stop"][0] == original["hooks"]["Stop"][0]
    uninstall_hooks("claude", path, tmp_path / "state")
    assert json.loads(path.read_text()) == original


def test_installed_command_works_from_unrelated_working_directory(tmp_path: Path) -> None:
    path = tmp_path / "hooks.json"
    state = tmp_path / "state with spaces"
    install_hooks("codex", path, state)
    (tmp_path / "busybar_codex.py").write_text("raise RuntimeError('shadow module executed')")
    config = json.loads(path.read_text())
    handler = config["hooks"]["UserPromptSubmit"][0]["hooks"][0]
    if sys.platform == "win32":
        command = ["powershell.exe", "-NoProfile", "-Command", handler["commandWindows"]]
    else:
        command = ["sh", "-c", handler["command"]]
    completed = subprocess.run(
        command,
        cwd=tmp_path,
        input=json.dumps(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": "test-session",
                "prompt": "PRIVATE",
            }
        ),
        text=True,
        capture_output=True,
        timeout=3,
    )
    assert completed.returncode == 0
    events = EventQueue(state / "queue").drain()
    assert len(events) == 1
    assert "PRIVATE" not in events[0].to_json()


def test_installer_cli_accepts_explicit_target(tmp_path: Path) -> None:
    target = tmp_path / "hooks.json"
    assert (
        main(
            [
                "--state-dir",
                str(tmp_path / "state"),
                "install-hooks",
                "--client",
                "codex",
                "--target",
                str(target),
            ],
            stdout=io.StringIO(),
            environ={},
        )
        == 0
    )
    assert "UserPromptSubmit" in json.loads(target.read_text())["hooks"]


@pytest.mark.skipif(not os.environ.get("BUSYBAR_TEST_WSL"), reason="optional real WSL interop")
def test_wsl_hooks_forward_stdin_to_shared_windows_state(tmp_path: Path) -> None:
    distro = os.environ["BUSYBAR_TEST_WSL"]
    target = tmp_path / "wsl-hooks.json"
    state = tmp_path / "shared-state"
    assert (
        main(
            [
                "--state-dir",
                str(state),
                "install-hooks",
                "--client",
                "codex",
                "--target",
                str(target),
                "--wsl-distro",
                distro,
            ],
            stdout=io.StringIO(),
        )
        == 0
    )
    config = json.loads(target.read_text())
    command = config["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]
    completed = subprocess.run(
        ["wsl.exe", "-d", distro, "--exec", "sh", "-c", command],
        input=json.dumps(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": "wsl-session",
                "prompt": "PRIVATE",
            }
        ),
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert completed.returncode == 0
    events = EventQueue(state / "queue").drain()
    assert len(events) == 1
    assert events[0].session_id == "wsl-session"


def test_reinstall_updates_owned_statusline_after_state_move(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    install_hooks("claude", path, tmp_path / "old")
    old = json.loads(path.read_text())["statusLine"]
    assert install_hooks("claude", path, tmp_path / "new")
    assert json.loads(path.read_text())["statusLine"] != old
    uninstall_hooks("claude", path, tmp_path / "another")
    assert "statusLine" not in json.loads(path.read_text())


def test_changed_user_statusline_is_preserved_despite_ownership_receipt(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    install_hooks("claude", path, tmp_path / "old")
    raw = json.loads(path.read_text())
    custom = {"type": "command", "command": "my-new-status"}
    raw["statusLine"] = custom
    path.write_text(json.dumps(raw))
    assert not install_hooks("claude", path, tmp_path / "new")
    uninstall_hooks("claude", path, tmp_path / "new")
    assert json.loads(path.read_text())["statusLine"] == custom
