from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from threading import Event

import pytest

from busybar_codex.local import ControlInbox
from busybar_codex.startup import StartupRegistration
from busybar_codex.tray import TrayActions, tray_image
from busybar_codex.tray_runtime import TrayController


class MemoryStartup:
    value: str | None = None

    def read(self) -> str | None:
        return self.value

    def write(self, value: str) -> None:
        self.value = value

    def delete(self) -> None:
        self.value = None


def test_menu_dispatch_changes_worker_startup_and_local_controls(tmp_path: Path) -> None:
    entered, exiting = Event(), Event()

    def runner(stop: Event, ready: Callable[[], None]) -> None:
        ready()
        entered.set()
        stop.wait(2)

    controller = TrayController(runner, ControlInbox(tmp_path))
    store = MemoryStartup()
    startup = StartupRegistration(["pythonw.exe", "-m", "busybar_codex.tray"], store)
    messages: list[str] = []
    actions = TrayActions(controller, startup, exiting, messages.append)
    assert not startup.enabled()
    actions.invoke("start")
    assert entered.wait(2)
    actions.invoke("hide")
    actions.invoke("show")
    assert ControlInbox(tmp_path).drain() == ["hide", "show"]
    actions.invoke("startup")
    assert startup.enabled()
    actions.invoke("startup")
    assert not startup.enabled()
    actions.invoke("exit")
    assert exiting.is_set()
    assert controller.close(2)
    assert not messages


def test_menu_conflict_is_reported_without_raw_command(tmp_path: Path) -> None:
    store = MemoryStartup()
    store.value = "PRIVATE other command"
    messages: list[str] = []
    controller = TrayController(lambda stop, ready: None, ControlInbox(tmp_path))
    actions = TrayActions(
        controller, StartupRegistration(["pythonw.exe"], store), Event(), messages.append
    )
    actions.invoke("startup")
    assert store.value == "PRIVATE other command"
    assert messages and all("PRIVATE" not in m for m in messages)


def test_tray_icon_has_transparent_margin_and_distinct_state_colors() -> None:
    running, stopped = tray_image("running"), tray_image("stopped")
    assert running.size == stopped.size == (64, 64)
    assert running.getpixel((0, 0)) == (0, 0, 0, 0)
    assert running.tobytes() != stopped.tobytes()


def test_registry_failure_does_not_escape_checked_menu_callback(tmp_path: Path) -> None:
    class BrokenStore(MemoryStartup):
        def read(self) -> str | None:
            raise OSError("PRIVATE")

    controller = TrayController(lambda stop, ready: None, ControlInbox(tmp_path))
    actions = TrayActions(
        controller, StartupRegistration(["pythonw.exe"], BrokenStore()), Event(), lambda _: None
    )
    assert not actions.startup_enabled()


def test_long_startup_path_does_not_prevent_manual_tray(tmp_path: Path) -> None:
    from busybar_codex.tray import optional_startup

    startup = optional_startup(["x" * 270], MemoryStartup())
    assert not startup.enabled()
    messages: list[str] = []
    controller = TrayController(lambda stop, ready: None, ControlInbox(tmp_path))
    actions = TrayActions(controller, startup, Event(), messages.append)
    actions.invoke("startup")
    assert messages == [
        "Login startup is unavailable from this installation path. Use a shorter path."
    ]


def test_native_refresh_failure_stops_worker_and_icon_safely(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    from typing import Any

    from busybar_codex.tray import run_menu

    class Icon:
        title = ""
        icon = tray_image("stopped")
        visible = False
        menu: object = None
        stopped = False

        def run(self, setup: Callable[[Any], None]) -> None:
            setup(self)

        def stop(self) -> None:
            self.stopped = True

        def update_menu(self) -> None:
            raise OSError("PRIVATE native error")

        def notify(self, message: str, title: str = "") -> None:
            pass

    icon = Icon()

    class Backend:
        def Icon(self, *args: Any, **kwargs: Any) -> Any:
            return icon

        def Menu(self, *items: object) -> object:
            return items

        def MenuItem(self, *args: Any, **kwargs: Any) -> object:
            return object()

    def runner(stop: Event, ready: Callable[[], None]) -> None:
        ready()
        stop.wait(2)

    controller = TrayController(runner, ControlInbox(tmp_path))
    run_menu(controller, StartupRegistration(["pythonw.exe"], MemoryStartup()), backend=Backend())
    assert icon.stopped
    assert controller.status == "stopped"
    assert "PRIVATE" not in caplog.text
