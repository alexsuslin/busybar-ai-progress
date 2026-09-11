from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import cast


class DisplayState(StrEnum):
    CODING = "coding"
    QUESTION = "question"
    DONE = "done"
    REGISTER = "register"
    REMOVE = "remove"


@dataclass(frozen=True, slots=True)
class SafeEvent:
    session_id: str
    turn_id: str | None
    state: DisplayState
    timestamp: str
    reason: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_json(cls, value: str) -> SafeEvent:
        decoded = cast(object, json.loads(value))
        if not isinstance(decoded, dict):
            raise ValueError("event must be an object")
        raw = cast(dict[str, object], decoded)
        session_id = raw.get("session_id")
        turn_id = raw.get("turn_id")
        timestamp = raw.get("timestamp")
        reason = raw.get("reason")
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("invalid session_id")
        if turn_id is not None and not isinstance(turn_id, str):
            raise ValueError("invalid turn_id")
        if not isinstance(timestamp, str):
            raise ValueError("invalid timestamp")
        if not isinstance(reason, str):
            raise ValueError("invalid reason")
        try:
            state = DisplayState(raw.get("state"))
            datetime.fromisoformat(timestamp)
        except (TypeError, ValueError) as error:
            raise ValueError("invalid event") from error
        return cls(session_id, turn_id, state, timestamp, reason)


def _asks_for_input(message: object) -> bool:
    if not isinstance(message, str):
        return False
    normalized = message.strip().casefold()
    phrases = (
        "please choose",
        "which option",
        "reply with",
        "ответь одним",
        "выбери вариант",
    )
    return normalized.endswith("?") or any(phrase in normalized for phrase in phrases)


def normalize_hook(
    payload: Mapping[str, object],
    now: datetime | None = None,
) -> SafeEvent | None:
    name = payload.get("hook_event_name")
    session_id = payload.get("session_id")
    if not isinstance(name, str) or not isinstance(session_id, str) or not session_id:
        return None

    mapping = {
        "UserPromptSubmit": (DisplayState.CODING, "prompt"),
        "PermissionRequest": (DisplayState.QUESTION, "permission"),
        "PostToolUse": (DisplayState.CODING, "tool_complete"),
        "Interrupt": (DisplayState.DONE, "interrupted"),
        "SessionEnd": (DisplayState.REMOVE, "session_end"),
        "SessionStart": (DisplayState.REGISTER, "session_start"),
    }
    if name == "PreToolUse":
        if payload.get("tool_name") != "request_user_input":
            return None
        state, reason = DisplayState.QUESTION, "user_input"
    elif name == "Stop":
        if _asks_for_input(payload.get("last_assistant_message")):
            state, reason = DisplayState.QUESTION, "final_question"
        else:
            state, reason = DisplayState.DONE, "stop"
    elif name in mapping:
        state, reason = mapping[name]
    else:
        return None

    turn_id = payload.get("turn_id")
    timestamp = (now or datetime.now(UTC)).isoformat()
    return SafeEvent(
        session_id=session_id,
        turn_id=turn_id if isinstance(turn_id, str) else None,
        state=state,
        timestamp=timestamp,
        reason=reason,
    )
