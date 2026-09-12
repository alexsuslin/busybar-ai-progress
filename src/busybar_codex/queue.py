from __future__ import annotations

import os
import tempfile
import time
import uuid
from pathlib import Path

from .events import SafeEvent
from .local import atomic_write


class EventQueue:
    """A lock-free, one-file-per-event queue for short-lived hook processes."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def put(self, event: SafeEvent) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.directory,
                prefix="event-",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write(event.to_json())
                handle.flush()
                os.fsync(handle.fileno())
            committed = self.directory / f"{time.time_ns():020d}-{uuid.uuid4().hex}.json"
            os.replace(temporary, committed)
            return committed
        except BaseException:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            raise

    def drain(self) -> list[SafeEvent]:
        self.directory.mkdir(parents=True, exist_ok=True)
        events: list[SafeEvent] = []
        for path in sorted(self.directory.glob("*.json")):
            try:
                event = SafeEvent.from_json(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._reject(path)
                continue
            events.append(event)
            path.unlink()
        return events

    def _reject(self, path: Path) -> None:
        rejected = self.directory / "rejected"
        rejected.mkdir(exist_ok=True)
        destination = rejected / path.name
        if destination.exists():
            destination = rejected / f"{path.stem}-{uuid.uuid4().hex}.json"
        atomic_write(destination, '{"reason":"invalid_event"}')
        path.unlink(missing_ok=True)
