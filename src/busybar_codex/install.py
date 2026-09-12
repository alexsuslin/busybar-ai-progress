from __future__ import annotations

import base64
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import cast

from .local import atomic_write
from .telemetry import object_map

MARKER = "BUSY Bar local status (busybar-codex)"


def _command(state_dir: Path, command: str, *, windows: bool, executable: str | None = None) -> str:
    parts = [
        executable or sys.executable,
        "-I",
        "-m",
        "busybar_codex",
        "--state-dir",
        str(state_dir.resolve()),
        command,
    ]
    if not windows:
        return shlex.join(parts)
    # EncodedCommand avoids nested PowerShell/Git-Bash quoting differences.
    script = "& " + " ".join("'" + part.replace("'", "''") + "'" for part in parts)
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return f"powershell.exe -NoProfile -NonInteractive -EncodedCommand {encoded}"


def _load(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict):
        raise ValueError("settings must be a JSON object")
    return cast(dict[str, object], raw)


def _owned(group: object) -> bool:
    hooks = object_map(group).get("hooks")
    return (
        isinstance(hooks, list)
        and bool(cast(list[object], hooks))
        and all(
            object_map(hook).get("statusMessage") == MARKER for hook in cast(list[object], hooks)
        )
    )


def _receipt_path(path: Path) -> Path:
    return path.with_name(path.name + ".busybar-statusline.json")


def _owned_statusline(path: Path, value: object) -> bool:
    # Only our exact last-installed value is owned; user edits always win.
    try:
        receipt = _load(_receipt_path(path))
    except (OSError, ValueError):
        return False
    return bool(receipt) and value == receipt


def install_hooks(
    client: str, path: Path, state_dir: Path, *, wsl_executable: str | None = None
) -> bool:
    """Merge only our hooks. Return whether our Claude status line is installed.

    Never back up whole settings files: they can contain credentials. Existing
    settings remain in place; uninstall removes only entries owned by this tool.
    """
    raw = _load(path)
    hooks = object_map(raw.get("hooks"))
    if "hooks" in raw and not isinstance(raw["hooks"], dict):
        raise ValueError("hooks must be an object")
    events = [
        "SessionStart",
        "UserPromptSubmit",
        "PermissionRequest",
        "PreToolUse",
        "PostToolUse",
        "Stop",
        "SessionEnd",
    ]
    if client == "codex":
        events.append("Interrupt")
    else:
        events.append("Notification")
    windows = sys.platform == "win32" and wsl_executable is None
    for name in events:
        old = hooks.get(name, [])
        if not isinstance(old, list):
            raise ValueError("hook groups must be arrays")
        groups = [group for group in cast(list[object], old) if not _owned(group)]
        handler: dict[str, object] = {
            "type": "command",
            "timeout": 3,
            "statusMessage": MARKER,
            "command": _command(state_dir, "hook", windows=windows, executable=wsl_executable),
        }
        if client == "codex":
            handler["commandWindows"] = _command(state_dir, "hook", windows=True)
        group: dict[str, object] = {"hooks": [handler]}
        if name == "PreToolUse":
            group["matcher"] = "^(request_user_input|AskUserQuestion)$"
        if name == "Notification":
            group["matcher"] = "^(permission_prompt|idle_prompt)$"
        groups.append(group)
        hooks[name] = groups
    raw["hooks"] = hooks
    statusline = {
        "type": "command",
        "command": _command(
            state_dir, "claude-statusline", windows=windows, executable=wsl_executable
        ),
    }
    if client == "claude" and (
        "statusLine" not in raw or _owned_statusline(path, raw.get("statusLine"))
    ):
        raw["statusLine"] = statusline
    atomic_write(path, json.dumps(raw, indent=2, ensure_ascii=False) + "\n")
    if client == "claude" and raw.get("statusLine") == statusline:
        atomic_write(_receipt_path(path), json.dumps(statusline) + "\n")
    return client != "claude" or raw.get("statusLine") == statusline


def uninstall_hooks(
    client: str, path: Path, state_dir: Path, *, wsl_executable: str | None = None
) -> None:
    if not path.exists():
        return
    raw = _load(path)
    hooks = object_map(raw.get("hooks"))
    for name in list(hooks):
        old = hooks[name]
        if isinstance(old, list):
            kept = [group for group in cast(list[object], old) if not _owned(group)]
            if len(kept) != len(cast(list[object], old)):
                if kept:
                    hooks[name] = kept
                else:
                    del hooks[name]
    if not hooks:
        raw.pop("hooks", None)
    statusline = {
        "type": "command",
        "command": _command(
            state_dir,
            "claude-statusline",
            windows=sys.platform == "win32" and wsl_executable is None,
            executable=wsl_executable,
        ),
    }
    if client == "claude" and (
        raw.get("statusLine") == statusline or _owned_statusline(path, raw.get("statusLine"))
    ):
        del raw["statusLine"]
    atomic_write(path, json.dumps(raw, indent=2, ensure_ascii=False) + "\n")
    if client == "claude":
        _receipt_path(path).unlink(missing_ok=True)


def wsl_paths(client: str, distro: str) -> tuple[Path, str]:
    if sys.platform != "win32" or not re.fullmatch(r"[A-Za-z0-9_.-]+", distro):
        raise ValueError("WSL installation requires Windows and a valid distribution name")

    def run(*args: str) -> str:
        result = subprocess.run(
            ["wsl.exe", "-d", distro, "--exec", *args],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        if result.returncode:
            raise ValueError("WSL command failed")
        return result.stdout.strip()

    home = run("printenv", "HOME")
    executable = run("wslpath", "-u", sys.executable)
    if not home.startswith("/") or not executable.startswith("/") or "\n" in home:
        raise ValueError("invalid WSL paths")
    filename = "hooks.json" if client == "codex" else "settings.json"
    target = Path(f"//wsl.localhost/{distro}{home}/.{client}/{filename}")
    return target, executable
