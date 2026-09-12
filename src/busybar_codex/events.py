from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import cast


def valid_identifier(value: str) -> bool:
    return re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value) is not None


SAFE_REASONS = frozenset(
    {
        "prompt",
        "permission",
        "tool_complete",
        "interrupted",
        "session_end",
        "session_start",
        "user_input",
        "notification",
        "final_question",
        "stop",
        "manual",
        "rollout_started",
        "rollout_complete",
        "rollout_interrupted",
    }
)


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
        if not isinstance(session_id, str) or not valid_identifier(session_id):
            raise ValueError("invalid session_id")
        if turn_id is not None and (not isinstance(turn_id, str) or not valid_identifier(turn_id)):
            raise ValueError("invalid turn_id")
        if not isinstance(timestamp, str):
            raise ValueError("invalid timestamp")
        if not isinstance(reason, str) or reason not in SAFE_REASONS:
            raise ValueError("invalid reason")
        try:
            state = DisplayState(raw.get("state"))
            if datetime.fromisoformat(timestamp).tzinfo is None:
                raise ValueError("timestamp requires timezone")
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
    if (
        not isinstance(name, str)
        or not isinstance(session_id, str)
        or not valid_identifier(session_id)
    ):
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
        if payload.get("tool_name") not in ("request_user_input", "AskUserQuestion"):
            return None
        state, reason = DisplayState.QUESTION, "user_input"
    elif name == "Notification":
        if payload.get("notification_type") not in ("permission_prompt", "idle_prompt"):
            return None
        state, reason = DisplayState.QUESTION, "notification"
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
    if turn_id is not None and (not isinstance(turn_id, str) or not valid_identifier(turn_id)):
        return None
    timestamp = (now or datetime.now(UTC)).isoformat()
    return SafeEvent(
        session_id=session_id,
        turn_id=turn_id if isinstance(turn_id, str) else None,
        state=state,
        timestamp=timestamp,
        reason=reason,
    )


def normalize_rollout_lifecycle(row: Mapping[str, object], session_id: str) -> SafeEvent | None:
    """Extract lifecycle fields only; never retain assistant text from the payload."""
    payload = row.get("payload")
    if row.get("type") != "event_msg" or not isinstance(payload, dict):
        return None
    raw = cast(dict[str, object], payload)
    mapping = {
        "task_started": (DisplayState.CODING, "rollout_started"),
        "task_complete": (DisplayState.DONE, "rollout_complete"),
        "turn_aborted": (DisplayState.DONE, "rollout_interrupted"),
    }
    kind, turn_id, timestamp = raw.get("type"), raw.get("turn_id"), row.get("timestamp")
    if (
        not isinstance(kind, str)
        or kind not in mapping
        or not valid_identifier(session_id)
        or not isinstance(turn_id, str)
        or not valid_identifier(turn_id)
        or not isinstance(timestamp, str)
        or len(timestamp) > 64
    ):
        return None
    try:
        instant = datetime.fromisoformat(timestamp)
        if instant.tzinfo is None or instant > datetime.now(UTC):
            return None
    except ValueError:
        return None
    state, reason = mapping[kind]
    return SafeEvent(session_id, turn_id, state, instant.isoformat(), reason)
