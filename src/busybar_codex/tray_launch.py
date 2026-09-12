from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import cast

from dotenv import dotenv_values

from .config import Config
from .local import InstanceLock, atomic_write

WINDOWS = sys.platform == "win32"

APP_ENV = frozenset(
    {
        "BUSYBAR_CODEX_ADDRESS",
        "BUSYBAR_CODEX_TOKEN",
        "BUSYBAR_CODEX_PRIORITY",
        "BUSYBAR_CODEX_APPLICATION_NAME",
        "BUSYBAR_CODEX_STALE_AFTER_SECONDS",
        "BUSYBAR_CODEX_POLL_INTERVAL_SECONDS",
        "BUSYBAR_CODEX_REQUEST_TIMEOUT_SECONDS",
        "BUSYBAR_CODEX_LOG_LEVEL",
        "BUSYBAR_CODEX_ANIMATIONS",
        "BUSYBAR_CODEX_CONFIG_DIR",
        "BUSYBAR_CODEX_STATE_DIR",
        "BUSYBAR_CODEX_CACHE_DIR",
        "BUSYBAR_CODEX_LOG_DIR",
        "CODEX_HOME",
    }
)


def _path(value: object, *, optional: bool = False) -> Path | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not 0 < len(value) <= 4096:
        raise ValueError("invalid launch path")
    if any(ord(char) < 32 for char in value) or not Path(value).is_absolute():
        raise ValueError("invalid launch path")
    return Path(value)


@dataclass(frozen=True)
class LaunchProfile:
    working_directory: Path
    config_file: Path | None = None
    env_file: Path | None = None
    state_dir: Path | None = None


def save_profile(profile: LaunchProfile, path: Path) -> None:
    values = {
        key: str(value) if value is not None else None for key, value in asdict(profile).items()
    }
    for key, value in values.items():
        _path(value, optional=key != "working_directory")
    content = json.dumps(values)
    if len(content.encode("utf-8")) > 8192:
        raise ValueError("launch profile too large")
    atomic_write(path, content)


def load_profile(path: Path) -> LaunchProfile:
    with path.open("rb") as stream:
        content = stream.read(8193)
    if len(content) > 8192:
        raise ValueError("launch profile too large")
    raw: object = json.loads(content)
    if not isinstance(raw, dict):
        raise ValueError("invalid launch profile")
    values = cast(dict[str, object], raw)
    if set(values) != {
        "working_directory",
        "config_file",
        "env_file",
        "state_dir",
    }:
        raise ValueError("invalid launch profile")
    directory = _path(values["working_directory"])
    assert directory is not None
    return LaunchProfile(
        directory,
        _path(values["config_file"], optional=True),
        _path(values["env_file"], optional=True),
        _path(values["state_dir"], optional=True),
    )


def environment_for(profile: LaunchProfile, inherited: Mapping[str, str]) -> dict[str, str]:
    values: dict[str, str] = {}
    if profile.env_file is not None:
        with profile.env_file.open("rb") as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise ValueError("environment file too large")
        parsed = dotenv_values(stream=io.StringIO(raw.decode("utf-8-sig")), interpolate=False)
        values.update(
            {key: value for key, value in parsed.items() if key in APP_ENV and value is not None}
        )
    values.update(inherited)
    for key in APP_ENV:
        if (key.endswith("_DIR") or key == "CODEX_HOME") and (value := values.get(key)):
            values[key] = str((profile.working_directory / value).resolve())
    if profile.state_dir is not None:
        values["BUSYBAR_CODEX_STATE_DIR"] = str(profile.state_dir)
    return values


def tray_command(profile_path: Path, executable: Path | None = None) -> list[str]:
    pythonw = executable or Path(sys.executable).with_name("pythonw.exe")
    if pythonw.name.lower() != "pythonw.exe" or not pythonw.is_absolute() or not pythonw.is_file():
        raise ValueError("windowless Python unavailable")
    if not profile_path.is_absolute():
        raise ValueError("invalid launch profile path")
    return [str(pythonw), "-I", "-m", "busybar_codex.tray", "--profile", str(profile_path)]


def profile_location(config: Config) -> Path:
    key = hashlib.sha256(os.path.normcase(str(config.state_dir.resolve())).encode()).hexdigest()[
        :12
    ]
    return (config.config_dir / f"tray-{key}.json").resolve()


def launch_tray(profile: LaunchProfile, inherited: Mapping[str, str] | None = None) -> None:
    if not WINDOWS:
        raise ValueError("tray requires Windows")
    environment = environment_for(profile, os.environ if inherited is None else inherited)
    config = Config.load(profile.config_file, environment)
    profile = replace(
        profile,
        state_dir=config.state_dir.resolve(),
        config_file=(profile.config_file or config.config_dir / "config.toml").resolve(),
    )
    path = profile_location(config)
    command = tray_command(path.resolve())
    # Do not overwrite a running tray's profile or create a second tray.
    with InstanceLock(config.state_dir / "tray.lock"):
        save_profile(profile, path)
    subprocess.Popen(
        command,
        cwd=profile.working_directory,
        env=environment,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=0x08000000,
    )
