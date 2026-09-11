import json
from datetime import UTC, datetime

import pytest

from busybar_codex.events import DisplayState, normalize_hook

NOW = datetime(2026, 9, 11, tzinfo=UTC)


@pytest.mark.parametrize(
    ("payload", "expected_state", "expected_reason"),
    [
        (
            {"hook_event_name": "SessionStart", "session_id": "s1"},
            DisplayState.REGISTER,
            "session_start",
        ),
        (
            {"hook_event_name": "UserPromptSubmit", "session_id": "s1"},
            DisplayState.CODING,
            "prompt",
        ),
        (
            {"hook_event_name": "PermissionRequest", "session_id": "s1"},
            DisplayState.QUESTION,
            "permission",
        ),
        (
            {"hook_event_name": "PostToolUse", "session_id": "s1"},
            DisplayState.CODING,
            "tool_complete",
        ),
        ({"hook_event_name": "Stop", "session_id": "s1"}, DisplayState.DONE, "stop"),
        ({"hook_event_name": "Interrupt", "session_id": "s1"}, DisplayState.DONE, "interrupted"),
        ({"hook_event_name": "SessionEnd", "session_id": "s1"}, DisplayState.REMOVE, "session_end"),
    ],
)
def test_hook_event_maps_to_safe_transition(
    payload: dict[str, object],
    expected_state: DisplayState,
    expected_reason: str,
) -> None:
    event = normalize_hook(payload, NOW)

    assert event is not None
    assert event.state is expected_state
    assert event.reason == expected_reason
    assert event.timestamp == "2026-09-11T00:00:00+00:00"


def test_request_user_input_becomes_question() -> None:
    event = normalize_hook(
        {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": "request_user_input",
        },
        NOW,
    )

    assert event is not None
    assert event.state is DisplayState.QUESTION
    assert event.reason == "user_input"


@pytest.mark.parametrize(
    "message",
    ["Which option should I use?", "Please choose one option.", "Ответь одним вариантом."],
)
def test_stop_with_blocking_question_stays_question(message: str) -> None:
    event = normalize_hook(
        {
            "hook_event_name": "Stop",
            "session_id": "s1",
            "last_assistant_message": message,
        },
        NOW,
    )

    assert event is not None
    assert event.state is DisplayState.QUESTION
    assert event.reason == "final_question"


def test_private_hook_fields_are_not_serialized() -> None:
    secret = "do not persist this"
    event = normalize_hook(
        {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "turn_id": "t1",
            "prompt": secret,
            "tool_name": "request_user_input",
            "tool_input": {"questions": [{"question": secret}]},
            "last_assistant_message": secret,
        },
        NOW,
    )

    assert event is not None
    encoded = event.to_json()
    assert secret not in encoded
    assert json.loads(encoded) == {
        "reason": "user_input",
        "session_id": "s1",
        "state": "question",
        "timestamp": "2026-09-11T00:00:00+00:00",
        "turn_id": "t1",
    }


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"hook_event_name": "FutureHook", "session_id": "s1"},
        {"hook_event_name": "Stop"},
        {"hook_event_name": 123, "session_id": "s1"},
        {"hook_event_name": "Stop", "session_id": 123},
        {"hook_event_name": "PreToolUse", "session_id": "s1", "tool_name": "exec_command"},
    ],
)
def test_irrelevant_or_invalid_payload_is_ignored(payload: dict[str, object]) -> None:
    assert normalize_hook(payload, NOW) is None
