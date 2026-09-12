"""Opt-in Windows login startup scoped to one application-owned Run value."""

import subprocess
import sys
import unicodedata
from collections.abc import Sequence
from typing import Protocol, cast

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_VALUE = "BusyBarAIProgress"
_MAX_COMMAND_UNITS = 260


class StartupConflictError(ValueError):
    """The existing startup value is not owned by this launch command."""


class RunStore(Protocol):
    """Storage for the single application startup value."""

    def read(self) -> str | None: ...

    def write(self, value: str) -> None: ...

    def delete(self) -> None: ...


def _format_command(command: object) -> str:
    if not isinstance(command, Sequence) or isinstance(command, (str, bytes)):
        raise ValueError("startup_command_invalid")
    arguments = cast(Sequence[object], command)
    if not 0 < len(arguments) <= _MAX_COMMAND_UNITS:
        raise ValueError("startup_command_invalid")
    parts: list[str] = []
    for part in arguments:
        if (
            not isinstance(part, str)
            or not part.strip()
            or len(part) > _MAX_COMMAND_UNITS
            or any(unicodedata.category(char) in {"Cc", "Cs"} for char in part)
        ):
            raise ValueError("startup_command_invalid")
        parts.append(part)
    value = subprocess.list2cmdline(parts)
    if len(value.encode("utf-16-le")) // 2 > _MAX_COMMAND_UNITS:
        raise ValueError("startup_command_too_long")
    return value


class _RegistryRunStore:
    def __init__(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("startup_windows_required")

    def read(self) -> str | None:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
                value, kind = winreg.QueryValueEx(key, _RUN_VALUE)
        except FileNotFoundError:
            return None
        if kind != winreg.REG_SZ or not isinstance(value, str):
            raise StartupConflictError("startup_value_conflict")
        return value

    def write(self, value: str) -> None:
        import winreg

        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, _RUN_VALUE, 0, winreg.REG_SZ, value)

    def delete(self) -> None:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, _RUN_VALUE)
        except FileNotFoundError:
            pass


class StartupRegistration:
    """Manage startup only when its complete command matches this instance."""

    def __init__(self, command: Sequence[str], store: RunStore | None = None) -> None:
        self._command = _format_command(command)
        self._store: RunStore = store if store is not None else _RegistryRunStore()

    def enabled(self) -> bool:
        try:
            return self._store.read() == self._command
        except StartupConflictError:
            return False
        except OSError:
            raise RuntimeError("startup_store_failed") from None

    def set_enabled(self, enabled: bool) -> None:
        try:
            existing = self._store.read()
            if existing is not None and existing != self._command:
                raise StartupConflictError("startup_value_conflict")
            if enabled and existing is None:
                self._store.write(self._command)
            elif not enabled and existing is not None:
                self._store.delete()
        except OSError:
            raise RuntimeError("startup_store_failed") from None
