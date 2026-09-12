from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import cast

from .events import DisplayState
from .state import SessionRecord, SessionReducer
from .telemetry import Telemetry, object_map


class Dashboard:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.hidden = False
        self.selected_id: str | None = None
        self._clock = clock
        self._manual_until = 0.0

    def select(self, reducer: SessionReducer) -> SessionRecord | None:
        visible = reducer.visible_records
        if self.selected_id not in visible or self._clock() >= self._manual_until:
            priority = {DisplayState.QUESTION: 0, DisplayState.CODING: 1, DisplayState.DONE: 2}
            records = sorted(
                visible.values(),
                key=lambda r: (
                    priority[r.state],
                    -datetime.fromisoformat(r.timestamp).timestamp(),
                    reducer.session_number(r.session_id),
                ),
            )
            self.selected_id = records[0].session_id if records else None
        return visible.get(self.selected_id) if self.selected_id is not None else None

    def move(self, delta: int, reducer: SessionReducer) -> None:
        record = self.select(reducer)
        if record is None:
            return
        ids = sorted(reducer.visible_records, key=reducer.session_number)
        self.selected_id = ids[(ids.index(record.session_id) + delta) % len(ids)]
        self._manual_until = self._clock() + 30.0

    def action(self, value: str | int, reducer: SessionReducer) -> None:
        if isinstance(value, int):
            self.move(value, reducer)
        elif value in {"next", "previous"}:
            self.move(1 if value == "next" else -1, reducer)
        elif value == "dismiss":
            record = self.select(reducer)
            if record is not None:
                self.dismiss(record.session_id, reducer)
        elif value in {"hide", "show"}:
            self.hidden = value == "hide"

    def dismiss(self, session_id: str, reducer: SessionReducer) -> None:
        reducer.dismiss(session_id)
        self.selected_id = None
        self._manual_until = 0.0


def input_actions(message: object) -> list[str | int]:
    result: list[str | int] = []
    updates = object_map(message).get("updates")
    if not isinstance(updates, list):
        return result
    for update in cast(list[object], updates):
        raw = object_map(object_map(update).get("input"))
        button = object_map(raw.get("button_event"))
        if button.get("button") == "START" and button.get("action") == "PRESS":
            result.append("dismiss")
        delta = object_map(raw.get("encoder_event")).get("delta")
        if type(delta) is int and delta:
            result.append(delta)
    return result


class WorkActivity(StrEnum):
    THINK = "THINK"
    TOOL = "TOOL"
    CHECK = "CHECK"
    COMPACT = "COMPACT"


def activity_for(record: SessionRecord | None) -> WorkActivity | None:
    if record is None or record.state is not DisplayState.CODING:
        return None
    return {
        "prompt": WorkActivity.THINK,
        "rollout_started": WorkActivity.THINK,
        "tool_started": WorkActivity.TOOL,
        "tool_complete": WorkActivity.THINK,
        "user_input_complete": WorkActivity.THINK,
        "permission_check": WorkActivity.CHECK,
        "compact_started": WorkActivity.COMPACT,
        "compact_complete": WorkActivity.THINK,
    }.get(record.reason)


@dataclass(frozen=True, slots=True)
class DisplayFrame:
    state: DisplayState
    session_tag: str | None
    session_count: int
    question_count: int
    telemetry: Telemetry
    hidden: bool = False
    activity: WorkActivity | None = None
