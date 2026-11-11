from __future__ import annotations

from argparse import Namespace
from collections.abc import Callable
from pathlib import Path
from threading import Event

import pytest

from busybar_codex.cli import run_daemon
from busybar_codex.config import Config
from busybar_codex.local import AlreadyRunningError, ControlInbox, InstanceLock
from busybar_codex.tray_runtime import TrayController


def test_stop_is_cooperative_and_duplicate_start_is_rejected(tmp_path: Path) -> None:
    entered, released = Event(), Event()

    def runner(stop: Event, ready: Callable[[], None]) -> None:
        ready()
        entered.set()
        assert stop.wait(2)
        released.set()

    controller = TrayController(runner, ControlInbox(tmp_path))
    assert controller.start()
    assert entered.wait(2)
    assert not controller.start()
    controller.stop()
    assert released.wait(2)
    assert controller.close(2)
    assert controller.status == "stopped"
    assert not controller.start()


def test_restart_waits_for_old_cleanup_and_close_cancels_pending_restart(tmp_path: Path) -> None:
    first, cleanup, second = Event(), Event(), Event()
    calls: list[int] = []

    def runner(stop: Event, ready: Callable[[], None]) -> None:
        ready()
        calls.append(1)
        if len(calls) == 1:
            first.set()
            assert stop.wait(2)
            assert cleanup.wait(2)
        else:
            second.set()
            assert stop.wait(2)

    controller = TrayController(runner, ControlInbox(tmp_path))
    controller.start()
    assert first.wait(2)
    controller.restart()
    assert not second.wait(0.03)
    cleanup.set()
    assert second.wait(2)
    assert controller.close(2)
    assert calls == [1, 1]


def test_exit_cancels_restart_even_during_slow_cleanup(tmp_path: Path) -> None:
    entered, cleanup = Event(), Event()
    calls: list[int] = []

    def runner(stop: Event, ready: Callable[[], None]) -> None:
        ready()
        calls.append(1)
        entered.set()
        stop.wait(2)
        cleanup.wait(2)

    controller = TrayController(runner, ControlInbox(tmp_path))
    controller.start()
    assert entered.wait(2)
    controller.restart()
    assert not controller.close(0.01)
    cleanup.set()
    assert controller.close(2)
    assert calls == [1]


@pytest.mark.parametrize(
    "error, expected", [(AlreadyRunningError("PRIVATE"), "external"), (OSError("PRIVATE"), "error")]
)
def test_worker_failure_is_safe_and_retryable(
    tmp_path: Path, error: Exception, expected: str, caplog: pytest.LogCaptureFixture
) -> None:
    attempted = Event()

    def runner(stop: Event, ready: Callable[[], None]) -> None:
        ready()
        attempted.set()
        raise error

    controller = TrayController(runner, ControlInbox(tmp_path))
    controller.start()
    assert attempted.wait(2)
    assert controller.close(2)
    assert controller.status == expected
    assert "PRIVATE" not in caplog.text


def test_controls_use_existing_local_inbox_only_when_running(tmp_path: Path) -> None:
    entered = Event()

    def runner(stop: Event, ready: Callable[[], None]) -> None:
        ready()
        entered.set()
        stop.wait(2)

    inbox = ControlInbox(tmp_path)
    controller = TrayController(runner, inbox)
    assert not controller.control("hide")
    controller.start()
    assert entered.wait(2)
    assert controller.control("hide")
    assert controller.control("show")
    assert inbox.drain() == ["hide", "show"]
    with pytest.raises(ValueError):
        controller.control("approve")
    assert controller.close(2)


def test_cli_daemon_accepts_stop_event_and_releases_lock(tmp_path: Path) -> None:
    class Display:
        def probe(self) -> str:
            raise AssertionError("unexpected device access")

        def render(self, state: object) -> None:
            raise AssertionError("stop must prevent rendering")

    config = Config(state_dir=tmp_path)
    args = Namespace(no_input=True, no_telemetry=True, no_animation=False, codex_sessions_dir=None)
    stop = Event()
    stop.set()
    assert run_daemon(config, lambda _: Display(), args, stop_event=stop) == 0
    with InstanceLock(tmp_path / "daemon.lock"):
        pass


def test_controls_are_rejected_until_daemon_ownership_is_confirmed(tmp_path: Path) -> None:
    attempted, allow = Event(), Event()

    def runner(stop: Event, ready: Callable[[], None]) -> None:
        attempted.set()
        assert allow.wait(2)
        raise AlreadyRunningError("other daemon")

    inbox = ControlInbox(tmp_path)
    controller = TrayController(runner, inbox)
    controller.start()
    assert attempted.wait(2)
    assert controller.status == "starting"
    assert not controller.control("hide")
    allow.set()
    assert controller.close(2)
    assert inbox.drain() == []
