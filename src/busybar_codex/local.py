from __future__ import annotations

import errno
import hashlib
import json
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path
from types import TracebackType
from typing import BinaryIO

from .telemetry import Telemetry


def atomic_write(path: Path, content: str) -> None:
    """Callers must pass only normalized, privacy-safe data."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class MetadataStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def _path(self, session_id: str) -> Path:
        key = hashlib.sha256(session_id.encode()).hexdigest()
        return self.directory / f"{key}.json"

    def write(self, session_id: str, data: Telemetry) -> None:
        atomic_write(self._path(session_id), data.to_json())

    def read(self, session_id: str) -> Telemetry:
        path = self._path(session_id)
        try:
            if path.stat().st_size > 8192 or time.time() - path.stat().st_mtime > 86400:
                return Telemetry()
            return Telemetry.from_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return Telemetry()


class ControlInbox:
    ACTIONS = frozenset({"hide", "show", "dismiss", "next", "previous"})

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def put(self, action: str) -> None:
        if action not in self.ACTIONS:
            raise ValueError("invalid control action")
        atomic_write(
            self.directory / f"{time.time_ns():020d}-{uuid.uuid4().hex}.json", json.dumps(action)
        )

    def drain(self) -> list[str | int]:
        result: list[str | int] = []
        for path in sorted(self.directory.glob("*.json"))[:128]:
            try:
                if path.stat().st_size <= 64:
                    action = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(action, str) and action in self.ACTIONS:
                        result.append(action)
            except (OSError, ValueError):
                pass
            path.unlink(missing_ok=True)
        return result


class AlreadyRunningError(OSError):
    """Another process owns this state directory lock."""


class InstanceLock:
    """OS lock is released automatically even if the daemon process crashes."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle: BinaryIO | None = None

    def __enter__(self) -> InstanceLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
        except OSError:
            handle.close()
            raise
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            handle.close()
            if error.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                raise AlreadyRunningError("another daemon is running") from None
            raise
        self.handle = handle
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self.handle is not None:
            self.handle.close()
            self.handle = None
