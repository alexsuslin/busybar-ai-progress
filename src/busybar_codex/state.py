from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from .events import DisplayState, SafeEvent


@dataclass(frozen=True, slots=True)
class SessionRecord:
    session_id: str
    turn_id: str | None
    state: DisplayState
    timestamp: str
    reason: str

    @classmethod
    def from_event(cls, event: SafeEvent, state: DisplayState | None = None) -> SessionRecord:
        return cls(
            session_id=event.session_id,
            turn_id=event.turn_id,
            state=event.state if state is None else state,
            timestamp=event.timestamp,
            reason=event.reason,
        )


class SessionReducer:
    """Reduce per-session events into one display state."""

    def __init__(
        self,
        stale_after_seconds: int,
        records: dict[str, SessionRecord] | None = None,
    ) -> None:
        self.stale_after_seconds = stale_after_seconds
        self.records = records or {}

    def apply(self, event: SafeEvent) -> DisplayState:
        event_time = datetime.fromisoformat(event.timestamp)
        previous = self.records.get(event.session_id)
        if previous is not None and event_time < datetime.fromisoformat(previous.timestamp):
            return self.aggregate(event_time)

        if event.state is DisplayState.REMOVE:
            self.records.pop(event.session_id, None)
        elif event.state is DisplayState.REGISTER:
            self.records.setdefault(
                event.session_id,
                SessionRecord.from_event(event, DisplayState.DONE),
            )
        elif event.reason == "tool_complete" and (
            previous is None or previous.state is not DisplayState.QUESTION
        ):
            pass
        else:
            self.records[event.session_id] = SessionRecord.from_event(event)
        return self.aggregate(event_time)

    def aggregate(self, now: datetime | None = None) -> DisplayState:
        instant = now or datetime.now(UTC)
        stale = [
            session_id
            for session_id, record in self.records.items()
            if (instant - datetime.fromisoformat(record.timestamp)).total_seconds()
            > self.stale_after_seconds
        ]
        for session_id in stale:
            del self.records[session_id]

        if any(record.state is DisplayState.QUESTION for record in self.records.values()):
            return DisplayState.QUESTION
        if any(record.state is DisplayState.CODING for record in self.records.values()):
            return DisplayState.CODING
        return DisplayState.DONE

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "records": [asdict(self.records[key]) for key in sorted(self.records)],
        }
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f"{path.name}-",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                json.dump(payload, handle, separators=(",", ":"), sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except BaseException:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            raise

    @classmethod
    def load(cls, path: Path, stale_after_seconds: int) -> SessionReducer:
        if not path.exists():
            return cls(stale_after_seconds)
        try:
            decoded = cast(object, json.loads(path.read_text(encoding="utf-8")))
            if not isinstance(decoded, dict):
                raise ValueError
            raw = cast(dict[str, object], decoded)
            if raw.get("version") != 1:
                raise ValueError
            decoded_items = raw.get("records")
            if not isinstance(decoded_items, list):
                raise ValueError
            items = cast(list[object], decoded_items)
            records: dict[str, SessionRecord] = {}
            for item in items:
                safe = SafeEvent.from_json(json.dumps(item))
                if safe.state in {DisplayState.REGISTER, DisplayState.REMOVE}:
                    raise ValueError
                records[safe.session_id] = SessionRecord.from_event(safe)
        except (OSError, TypeError, ValueError) as error:
            raise ValueError("invalid state snapshot") from error
        return cls(stale_after_seconds, records)
