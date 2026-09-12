from __future__ import annotations

import argparse
import ctypes
import importlib
import logging
import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from threading import Event
from typing import Protocol, cast

from PIL import Image, ImageDraw

from .busybar import BusyBarDisplay
from .cli import configure_logging, run_daemon
from .config import Config
from .local import AlreadyRunningError, ControlInbox, InstanceLock
from .startup import RunStore, StartupConflictError, StartupRegistration
from .tray_launch import (
    LaunchProfile,
    environment_for,
    load_profile,
    profile_location,
    save_profile,
    tray_command,
)
from .tray_runtime import TrayController

logger = logging.getLogger(__name__)
TITLE = "BUSY Bar AI Progress"
LABELS = {
    "starting": "Starting",
    "running": "Running",
    "stopping": "Stopping",
    "stopped": "Stopped",
    "external": "Another daemon is running",
    "error": "Daemon error",
}


class TrayIcon(Protocol):
    title: str
    icon: Image.Image
    visible: bool

    def run(self, setup: Callable[[TrayIcon], None]) -> None: ...
    def stop(self) -> None: ...
    def update_menu(self) -> None: ...
    def notify(self, message: str, title: str = TITLE) -> None: ...


class TrayBackend(Protocol):
    def Icon(self, name: str, icon: Image.Image, title: str, menu: object) -> TrayIcon: ...
    def Menu(self, *items: object) -> object: ...
    def MenuItem(
        self,
        text: str | Callable[[object], str],
        action: Callable[[TrayIcon, object], None] | None,
        *,
        enabled: bool | Callable[[object], bool] = True,
        checked: Callable[[object], bool] | None = None,
    ) -> object: ...


def tray_image(status: str) -> Image.Image:
    colors = {
        "running": "#38bdf8",
        "starting": "#a78bfa",
        "stopping": "#fbbf24",
        "external": "#fbbf24",
        "error": "#fb7185",
    }
    image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((4, 13, 59, 50), radius=9, fill="#111827", outline="#9ca3af", width=2)
    draw.rounded_rectangle((11, 22, 52, 41), radius=3, fill=colors.get(status, "#64748b"))
    for x in (21, 32, 43):
        draw.line((x, 25, x, 38), fill="#111827", width=3)
    return image


class StartupToggle(Protocol):
    def enabled(self) -> bool: ...
    def set_enabled(self, enabled: bool) -> None: ...


class StartupUnavailableError(ValueError):
    pass


class UnavailableStartup:
    def enabled(self) -> bool:
        return False

    def set_enabled(self, enabled: bool) -> None:
        if enabled:
            raise StartupUnavailableError("startup_path_unavailable")


def optional_startup(command: Sequence[str], store: RunStore | None = None) -> StartupToggle:
    try:
        return StartupRegistration(command, store)
    except ValueError:
        return UnavailableStartup()


class TrayActions:
    def __init__(
        self,
        controller: TrayController,
        startup: StartupToggle,
        exiting: Event,
        notify: Callable[[str], None],
    ) -> None:
        self.controller = controller
        self.startup = startup
        self.exiting = exiting
        self.notify = notify

    def startup_enabled(self) -> bool:
        try:
            return self.startup.enabled()
        except (OSError, ValueError, RuntimeError):
            return False

    def invoke(self, action: str) -> None:
        try:
            if action == "start":
                self.controller.start()
            elif action == "stop":
                self.controller.stop()
            elif action == "restart":
                self.controller.restart()
            elif action in {"show", "hide"}:
                self.controller.control(action)
            elif action == "startup":
                self.startup.set_enabled(not self.startup.enabled())
            elif action == "exit":
                self.controller.stop()
                self.exiting.set()
        except StartupUnavailableError:
            self.notify(
                "Login startup is unavailable from this installation path. Use a shorter path."
            )
        except StartupConflictError:
            self.notify("A different startup entry already exists. It was preserved.")
        except Exception as error:
            logger.error("tray action failed error=%s", type(error).__name__)
            self.notify("The action failed. Check the app's safe diagnostic log.")


def run_menu(
    controller: TrayController, startup: StartupToggle, *, backend: TrayBackend | None = None
) -> None:
    native = backend or cast(TrayBackend, importlib.import_module("pystray"))
    exiting = Event()
    icon = native.Icon("busybar-ai-progress", tray_image("stopped"), TITLE, native.Menu())
    actions = TrayActions(controller, startup, exiting, lambda message: icon.notify(message, TITLE))

    def item(text: str, action: str, *, enabled: Callable[[object], bool] | None = None) -> object:
        def activate(_icon: TrayIcon, _item: object) -> None:
            actions.invoke(action)

        return native.MenuItem(
            text,
            activate,
            enabled=enabled or True,
            checked=(lambda _: actions.startup_enabled()) if action == "startup" else None,
        )

    # Dynamic menu labels are rebuilt only after a worker state change.
    menu = native.Menu(
        native.MenuItem(lambda _: "Status: " + LABELS[controller.status], None, enabled=False),
        item(
            "Start",
            "start",
            enabled=lambda _: controller.status in {"stopped", "error", "external"},
        ),
        item("Stop", "stop", enabled=lambda _: controller.status in {"running", "starting"}),
        item("Restart", "restart", enabled=lambda _: controller.status == "running"),
        item("Show display", "show", enabled=lambda _: controller.status == "running"),
        item("Hide display", "hide", enabled=lambda _: controller.status == "running"),
        item("Start with Windows", "startup"),
        item("Exit", "exit"),
    )
    # Menu is a documented mutable Icon property.
    cast(MenuIcon, icon).menu = menu

    def setup(visible_icon: TrayIcon) -> None:
        try:
            visible_icon.visible = True
            controller.start()
            previous = ""
            while not exiting.wait(0.25):
                status = controller.status
                if status != previous:
                    visible_icon.title = TITLE + " - " + LABELS[status]
                    visible_icon.icon = tray_image(status)
                    visible_icon.update_menu()
                    previous = status
            visible_icon.title = TITLE + " - Stopping"
        except Exception as error:
            logger.error("tray refresh failed error=%s", type(error).__name__)
        finally:
            exiting.set()
            while not controller.close(0.25):
                pass
            visible_icon.stop()

    try:
        icon.run(setup=setup)
    finally:
        exiting.set()
        while not controller.close(0.25):
            pass


class MenuIcon(TrayIcon, Protocol):
    menu: object


def run_profile(profile: LaunchProfile, profile_path: Path) -> None:
    environment = environment_for(profile, os.environ)
    os.chdir(profile.working_directory)
    os.environ.update(environment)
    config = Config.load(profile.config_file, environment)
    configure_logging(config)
    with InstanceLock(config.state_dir / "tray.lock"):
        args = argparse.Namespace(
            no_input=False, no_animation=False, no_telemetry=False, codex_sessions_dir=None
        )

        def runner(stop: Event, ready: Callable[[], None]) -> None:
            run_daemon(config, BusyBarDisplay.from_config, args, stop_event=stop, on_ready=ready)

        controller = TrayController(runner, ControlInbox(config.state_dir / "controls"))
        run_menu(controller, optional_startup(tray_command(profile_path)))


def show_error(message: str) -> None:
    if sys.platform == "win32":
        box = ctypes.WinDLL("user32", use_last_error=True).MessageBoxW
        box.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
        box.restype = ctypes.c_int
        box(None, message, TITLE, 0x10)
    elif sys.stderr is not None:
        sys.stderr.write(message + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    try:
        if sys.platform != "win32":
            raise ValueError("tray requires Windows")
        parser = argparse.ArgumentParser(prog="busybar-codex-tray")
        parser.add_argument("--profile", type=Path)
        parser.add_argument("--env-file", type=Path)
        parser.add_argument("--config", type=Path)
        parser.add_argument("--state-dir", type=Path)
        args = parser.parse_args(argv)
        if args.profile is not None:
            if any(value is not None for value in (args.env_file, args.config, args.state_dir)):
                raise ValueError("conflicting launch options")
            path = cast(Path, args.profile).resolve()
            profile = load_profile(path)
        else:
            profile = LaunchProfile(
                Path.cwd(),
                cast(Path, args.config).resolve() if args.config else None,
                cast(Path, args.env_file).resolve() if args.env_file else None,
                cast(Path, args.state_dir).resolve() if args.state_dir else None,
            )
            config = Config.load(profile.config_file, environment_for(profile, os.environ))
            profile = replace(
                profile,
                state_dir=config.state_dir.resolve(),
                config_file=(profile.config_file or config.config_dir / "config.toml").resolve(),
            )
            path = profile_location(config)
            with InstanceLock(config.state_dir / "tray.lock"):
                save_profile(profile, path)
        run_profile(profile, path)
        return 0
    except AlreadyRunningError:
        show_error("BUSY Bar tray is already running for this state directory.")
        return 1
    except Exception as error:
        logger.error("tray startup failed error=%s", type(error).__name__)
        show_error(
            "BUSY Bar tray could not start. Check the selected configuration and installation."
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
