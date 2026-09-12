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
        self._session_numbers: dict[str, int] = {}
        self._next_session_number = 1
        self.dismissed: dict[str, str] = {}
        self._number_sessions()

    def _number_sessions(self) -> None:
        self._session_numbers = {
            key: number for key, number in self._session_numbers.items() if key in self.records
        }
        for session_id in self.records:
            if session_id not in self._session_numbers:
                self._session_numbers[session_id] = self._next_session_number
                self._next_session_number += 1

    @property
    def visible_records(self) -> dict[str, SessionRecord]:
        return {key: record for key, record in self.records.items() if key not in self.dismissed}

    def dismiss(self, session_id: str) -> None:
        record = self.records.get(session_id)
        if record is not None:
            self.dismissed[session_id] = record.timestamp

    def session_number(self, session_id: str) -> int:
        return self._session_numbers[session_id]

    def session_label(self, session_id: str) -> str:
        return f"#{self.session_number(session_id):02d}"

    def apply(self, event: SafeEvent) -> DisplayState:
        event_time = datetime.fromisoformat(event.timestamp)
        previous = self.records.get(event.session_id)
        if previous is not None and event_time < datetime.fromisoformat(previous.timestamp):
            return self.aggregate(event_time)

        if event.state is DisplayState.REMOVE:
            self.records.pop(event.session_id, None)
            self.dismissed.pop(event.session_id, None)
        elif event.state is DisplayState.REGISTER:
            self.records.setdefault(
                event.session_id,
                SessionRecord.from_event(event, DisplayState.DONE),
            )
        elif event.reason == "tool_complete" and (
            previous is None
            or previous.state not in {DisplayState.QUESTION, DisplayState.CODING}
            or previous.reason == "final_question"
            or (
                previous.turn_id is not None
                and event.turn_id is not None
                and previous.turn_id != event.turn_id
            )
        ):
            pass
        else:
            self.records[event.session_id] = SessionRecord.from_event(event)
            dismissed_at = self.dismissed.get(event.session_id)
            if dismissed_at is not None and event_time > datetime.fromisoformat(dismissed_at):
                self.dismissed.pop(event.session_id)
        self._number_sessions()
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
            self._session_numbers.pop(session_id, None)
            self.dismissed.pop(session_id, None)

        if any(record.state is DisplayState.QUESTION for record in self.records.values()):
            return DisplayState.QUESTION
        if any(record.state is DisplayState.CODING for record in self.records.values()):
            return DisplayState.CODING
        return DisplayState.DONE

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "dismissed": self.dismissed,
            "session_numbers": self._session_numbers,
            "next_session_number": self._next_session_number,
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
        result = cls(stale_after_seconds, records)
        if "session_numbers" in raw:
            numbers = raw["session_numbers"]
            next_number = raw.get("next_session_number")
            if not isinstance(numbers, dict):
                raise ValueError("invalid session numbers")
            entries = cast(dict[str, object], numbers)
            if set(entries) != set(records) or any(
                type(number) is not int or not 1 <= number < 2**53 for number in entries.values()
            ):
                raise ValueError("invalid session numbers")
            validated = cast(dict[str, int], entries)
            if (
                len(set(validated.values())) != len(validated)
                or type(next_number) is not int
                or not max(validated.values(), default=0) < next_number <= 2**53
            ):
                raise ValueError("invalid session number counter")
            result._session_numbers = validated
            result._next_session_number = next_number
        dismissed = raw.get("dismissed", {})
        if not isinstance(dismissed, dict):
            raise ValueError("invalid dismissed sessions")
        for session_id, timestamp in cast(dict[str, object], dismissed).items():
            if session_id not in records or not isinstance(timestamp, str) or len(timestamp) > 64:
                raise ValueError("invalid dismissed sessions")
            try:
                instant = datetime.fromisoformat(timestamp)
                if instant.tzinfo is None or instant != datetime.fromisoformat(
                    records[session_id].timestamp
                ):
                    raise ValueError
            except ValueError:
                raise ValueError("invalid dismissed sessions") from None
            result.dismissed[session_id] = timestamp
        return result
