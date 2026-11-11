from __future__ import annotations

import importlib
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
from threading import Event, Thread
from typing import Any

import pytest

from busybar_codex.local import ControlInbox
from busybar_codex.startup import StartupRegistration
from busybar_codex.tray import run_menu
from busybar_codex.tray_runtime import TrayController

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or os.environ.get("BUSYBAR_TEST_TRAY") != "1",
    reason="opt-in Windows notification-area smoke test",
)


def test_native_menu_start_stop_restart_startup_controls_and_exit(tmp_path: Path) -> None:
    native = importlib.import_module("pystray")
    icons: list[Any] = []
    failures: list[BaseException] = []
    starts: list[int] = []

    class Backend:
        Menu = native.Menu
        MenuItem = native.MenuItem

        @staticmethod
        def Icon(*args: Any, **kwargs: Any) -> Any:
            icon = native.Icon(*args, **kwargs)
            icons.append(icon)
            return icon

    class Store:
        value: str | None = None

        def read(self) -> str | None:
            return self.value

        def write(self, value: str) -> None:
            self.value = value

        def delete(self) -> None:
            self.value = None

    def runner(stop: Event, ready: Callable[[], None]) -> None:
        starts.append(1)
        ready()
        stop.wait(15)

    def wait_until(predicate: Callable[[], bool]) -> None:
        deadline = time.monotonic() + 8
        while not predicate():
            assert time.monotonic() < deadline, "native menu timeout"
            time.sleep(0.02)

    inbox = ControlInbox(tmp_path)
    controller = TrayController(runner, inbox)
    store = Store()
    startup = StartupRegistration(["pythonw.exe", "-m", "busybar_codex.tray"], store)

    def drive() -> None:
        try:
            wait_until(
                lambda: bool(icons) and bool(icons[0].visible) and controller.status == "running"
            )
            icon = icons[0]
            items = icon.menu.items
            assert len(items) == 8
            assert str(items[0].text) == "Status: Running"
            items[5](icon)
            items[4](icon)
            assert inbox.drain() == ["hide", "show"]
            items[6](icon)
            assert startup.enabled()
            items[6](icon)
            assert not startup.enabled()
            items[2](icon)
            wait_until(lambda: controller.status == "stopped")
            items[1](icon)
            wait_until(lambda: len(starts) == 2 and controller.status == "running")
            items[3](icon)
            wait_until(lambda: len(starts) == 3 and controller.status == "running")
            items[7](icon)
        except BaseException as error:
            failures.append(error)
            if icons:
                icons[0].stop()

    driver = Thread(target=drive, daemon=True)
    driver.start()
    run_menu(controller, startup, backend=Backend())
    driver.join(10)
    assert not driver.is_alive()
    assert not failures, [type(error).__name__ for error in failures]
    assert controller.status == "stopped"
    assert store.value is None
