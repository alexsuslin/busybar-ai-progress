from __future__ import annotations

import json
from pathlib import Path

import pytest

from busybar_codex.tray_launch import (
    LaunchProfile,
    environment_for,
    load_profile,
    save_profile,
    tray_command,
)


def test_profile_roundtrip_contains_only_absolute_paths(tmp_path: Path) -> None:
    profile = LaunchProfile(
        tmp_path, env_file=tmp_path / "settings.env", state_dir=tmp_path / "state"
    )
    path = tmp_path / "tray.json"
    save_profile(profile, path)
    assert load_profile(path) == profile
    data = json.loads(path.read_text())
    assert set(data) == {"working_directory", "config_file", "env_file", "state_dir"}
    assert "TOKEN" not in path.read_text()


@pytest.mark.parametrize(
    "payload",
    ["[]", "{}", '{"working_directory": "relative"}', "x" * 8193, '{"working_directory": true}'],
)
def test_invalid_profile_is_rejected(tmp_path: Path, payload: str) -> None:
    path = tmp_path / "launch.json"
    path.write_text(payload)
    with pytest.raises(ValueError):
        load_profile(path)


def test_environment_is_filtered_without_interpolation_and_inherited_values_win(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "BUSYBAR_CODEX_TOKEN=synthetic-${PRIVATE}\nBUSYBAR_CODEX_ADDRESS=10.0.0.1\nPATH=bad\nPYTHONPATH=bad\nBUSYBAR_CODEX_STATE_DIR=state\n"
    )
    profile = LaunchProfile(tmp_path, env_file=env_file)
    env = environment_for(profile, {"BUSYBAR_CODEX_ADDRESS": "10.0.0.2", "PATH": "original"})
    assert env["BUSYBAR_CODEX_TOKEN"] == "synthetic-${PRIVATE}"
    assert env["BUSYBAR_CODEX_ADDRESS"] == "10.0.0.2"
    assert env["PATH"] == "original"
    assert "PYTHONPATH" not in env
    assert env["BUSYBAR_CODEX_STATE_DIR"] == str(tmp_path / "state")


def test_env_size_is_bounded_and_missing_file_not_ignored(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    profile = LaunchProfile(tmp_path, env_file=env_file)
    with pytest.raises(OSError):
        environment_for(profile, {})
    env_file.write_text("x" * 65537)
    with pytest.raises(ValueError):
        environment_for(profile, {})


def test_windowless_command_keeps_paths_as_separate_arguments(tmp_path: Path) -> None:
    python = tmp_path / "my env" / "pythonw.exe"
    python.parent.mkdir()
    python.touch()
    path = tmp_path / "settings folder" / "launch.json"
    assert tray_command(path, python) == [
        str(python),
        "-I",
        "-m",
        "busybar_codex.tray",
        "--profile",
        str(path),
    ]
    with pytest.raises(ValueError):
        tray_command(path, tmp_path / "python.exe")


def test_cli_launch_is_detached_and_does_not_persist_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import io
    import subprocess
    import sys
    from typing import Any

    from busybar_codex import tray_launch
    from busybar_codex.cli import main

    pythonw = tmp_path / "pythonw.exe"
    pythonw.touch()
    monkeypatch.setattr(tray_launch, "WINDOWS", True)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "python.exe"))
    env = {
        f"BUSYBAR_CODEX_{kind}_DIR": str(tmp_path / kind.lower())
        for kind in ("CONFIG", "STATE", "CACHE", "LOG")
    }
    env["BUSYBAR_CODEX_TOKEN"] = "synthetic-test-secret"
    captured: list[tuple[list[str], dict[str, Any]]] = []

    def spawn(command: list[str], **kwargs: Any) -> object:
        captured.append((command, kwargs))
        return object()

    monkeypatch.setattr(subprocess, "Popen", spawn)
    output = io.StringIO()
    assert main(["tray"], environ=env, stdout=output) == 0
    assert len(captured) == 1
    command, options = captured[0]
    assert command[:5] == [str(pythonw), "-I", "-m", "busybar_codex.tray", "--profile"]
    assert options["creationflags"] == 0x08000000
    assert options["stdin"] == options["stdout"] == options["stderr"] == subprocess.DEVNULL
    saved = Path(command[5]).read_text()
    assert "synthetic-test-secret" not in saved
    assert "launch requested" in output.getvalue()


def test_tray_launch_rejected_on_non_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from busybar_codex import tray_launch
    from busybar_codex.tray_launch import launch_tray

    monkeypatch.setattr(tray_launch, "WINDOWS", False)
    with pytest.raises(ValueError, match="Windows"):
        launch_tray(LaunchProfile(tmp_path), {})


def test_profiles_for_distinct_state_directories_cannot_overwrite_each_other(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess
    import sys

    from busybar_codex import tray_launch
    from busybar_codex.local import InstanceLock

    pythonw = tmp_path / "pythonw.exe"
    pythonw.touch()
    monkeypatch.setattr(tray_launch, "WINDOWS", True)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "python.exe"))
    commands: list[list[str]] = []

    def spawn(command: list[str], **kwargs: object) -> None:
        commands.append(command)

    monkeypatch.setattr(subprocess, "Popen", spawn)
    env = {"BUSYBAR_CODEX_CONFIG_DIR": str(tmp_path / "config")}
    a = LaunchProfile(tmp_path, state_dir=tmp_path / "a")
    b = LaunchProfile(tmp_path, state_dir=tmp_path / "b")
    tray_launch.launch_tray(a, env)
    first = Path(commands[0][-1]).read_bytes()
    with InstanceLock(tmp_path / "a" / "tray.lock"):
        tray_launch.launch_tray(b, env)
    assert commands[0][-1] != commands[1][-1]
    assert Path(commands[0][-1]).read_bytes() == first
