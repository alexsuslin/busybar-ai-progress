from __future__ import annotations

import logging
from collections.abc import Callable
from threading import Event, RLock, Thread

from .local import AlreadyRunningError, ControlInbox

logger = logging.getLogger(__name__)


class TrayController:
    """Own one cooperative worker; never terminate an unrelated daemon."""

    def __init__(
        self, runner: Callable[[Event, Callable[[], None]], None], controls: ControlInbox
    ) -> None:
        self._runner = runner
        self._controls = controls
        self._lock = RLock()
        self._thread: Thread | None = None
        self._stop = Event()
        self._restart = False
        self._closed = False
        self._status = "stopped"

    @property
    def status(self) -> str:
        with self._lock:
            return self._status

    def start(self) -> bool:
        with self._lock:
            if self._closed or self._thread is not None:
                return False
            self._stop = Event()
            self._status = "starting"
            self._thread = Thread(target=self._work, args=(self._stop,), name="busybar-daemon")
            self._thread.start()
            return True

    def _work(self, stop: Event) -> None:
        outcome = "stopped"
        try:
            self._runner(stop, self._ready)
        except AlreadyRunningError:
            outcome = "external"
        except Exception as error:
            outcome = "error"
            logger.error("tray worker failed error=%s", type(error).__name__)
        finally:
            with self._lock:
                restart = self._restart and not self._closed
                self._restart = False
                self._thread = None
                self._status = outcome
                if restart:
                    self.start()

    def _ready(self) -> None:
        with self._lock:
            if not self._stop.is_set():
                self._status = "running"

    def stop(self) -> None:
        with self._lock:
            self._restart = False
            if self._thread is not None:
                self._status = "stopping"
                self._stop.set()

    def restart(self) -> bool:
        with self._lock:
            if self._closed:
                return False
            if self._thread is None:
                return self.start()
            self._restart = True
            self._status = "stopping"
            self._stop.set()
            return True

    def close(self, timeout: float = 10) -> bool:
        with self._lock:
            self._closed = True
            self.stop()
            thread = self._thread
        if thread is not None:
            thread.join(timeout)
            return not thread.is_alive()
        return True

    def control(self, action: str) -> bool:
        if action not in ControlInbox.ACTIONS:
            raise ValueError("invalid control action")
        with self._lock:
            if self._status != "running":
                return False
            self._controls.put(action)
            return True
