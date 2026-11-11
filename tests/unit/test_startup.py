from collections.abc import Sequence
from typing import cast

import pytest

from busybar_codex.startup import StartupConflictError, StartupRegistration


class MemoryRunStore:
    def __init__(self, value: str | None = None) -> None:
        self.value = value
        self.mutations: list[str] = []
        self.reads = 0

    def read(self) -> str | None:
        self.reads += 1
        return self.value

    def write(self, value: str) -> None:
        self.value = value
        self.mutations.append("write")

    def delete(self) -> None:
        self.value = None
        self.mutations.append("delete")


def test_startup_defaults_off_without_registry_mutation() -> None:
    store = MemoryRunStore()
    registration = StartupRegistration(["pythonw.exe", "-m", "busybar_codex.tray"], store)
    assert not registration.enabled()
    assert store.mutations == []


def test_enable_quotes_windows_paths_and_is_idempotent() -> None:
    store = MemoryRunStore()
    registration = StartupRegistration(
        [
            r"C:\Program Files\Python\pythonw.exe",
            "-m",
            "busybar_codex.tray",
            r"D:\My App\profile.json",
        ],
        store,
    )
    registration.set_enabled(True)
    assert store.value == (
        r'"C:\Program Files\Python\pythonw.exe" -m busybar_codex.tray "D:\My App\profile.json"'
    )
    assert registration.enabled()
    registration.set_enabled(True)
    assert store.mutations == ["write"]


def test_disable_removes_only_exact_owned_command_and_is_idempotent() -> None:
    store = MemoryRunStore("pythonw.exe -m busybar_codex.tray")
    registration = StartupRegistration(["pythonw.exe", "-m", "busybar_codex.tray"], store)
    assert registration.enabled()
    registration.set_enabled(False)
    assert store.value is None
    assert not registration.enabled()
    registration.set_enabled(False)
    assert store.mutations == ["delete"]


@pytest.mark.parametrize("enabled", [True, False])
def test_conflicting_value_is_preserved_on_enable_and_disable(enabled: bool) -> None:
    store = MemoryRunStore("PRIVATE other command")
    registration = StartupRegistration(["pythonw.exe"], store)
    assert not registration.enabled()
    with pytest.raises(StartupConflictError) as error:
        registration.set_enabled(enabled)
    assert "PRIVATE" not in str(error.value)
    assert store.value == "PRIVATE other command"
    assert store.mutations == []


@pytest.mark.parametrize(
    "command",
    [
        [],
        [""],
        ["  "],
        ["pythonw.exe", ""],
        ["bad\x00.exe"],
        ["bad\n.exe"],
        ["bad\t.exe"],
        ["bad\x7f.exe"],
        ["bad\x85.exe"],
        ["bad\ud800.exe"],
        [None],
        [1],
        "pythonw.exe",
        None,
    ],
)
def test_invalid_command_fails_before_store_access(command: object) -> None:
    store = MemoryRunStore()
    with pytest.raises(ValueError) as error:
        StartupRegistration(cast(Sequence[str], command), store)
    assert "bad" not in str(error.value)
    assert store.reads == 0
    assert store.mutations == []


@pytest.mark.parametrize("command", [["x" * 261], ["x" * 257 + " y"], ["x" * 259 + "😀"]])
def test_oversized_encoded_command_is_rejected_before_store_access(command: list[str]) -> None:
    store = MemoryRunStore()
    with pytest.raises(ValueError):
        StartupRegistration(command, store)
    assert store.reads == 0
    assert store.mutations == []


@pytest.mark.parametrize("command", [["x" * 260], ["x" * 258 + "😀"]])
def test_exact_utf16_command_limit_is_accepted(command: list[str]) -> None:
    store = MemoryRunStore()
    registration = StartupRegistration(command, store)
    registration.set_enabled(True)
    assert registration.enabled()
    assert store.value == command[0]


def test_default_registry_store_is_windows_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.platform", "linux")
    with pytest.raises(RuntimeError, match="startup_windows_required"):
        StartupRegistration(["pythonw.exe"])


def test_store_failure_does_not_expose_raw_exception() -> None:
    class FailingStore(MemoryRunStore):
        def read(self) -> str | None:
            raise OSError("PRIVATE command details")

    registration = StartupRegistration(["pythonw.exe"], FailingStore())
    with pytest.raises(RuntimeError) as error:
        registration.set_enabled(True)
    assert "PRIVATE" not in str(error.value)
    assert error.value.__suppress_context__
