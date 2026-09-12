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
            DisplayState.CODING,
            "permission_check",
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
    [
        "Which option should I use?",
        "Please choose one option.",
        "Please confirm that I may publish the release?",
        "Please provide the required project ID.",
        "Ответь одним вариантом.",
        "Подтвердите, можно ли публиковать релиз?",
        "Выберите вариант для продолжения.",
    ],
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
        {"hook_event_name": "PreToolUse", "session_id": "s1"},
    ],
)
def test_irrelevant_or_invalid_payload_is_ignored(payload: dict[str, object]) -> None:
    assert normalize_hook(payload, NOW) is None


def test_naive_timestamp_is_rejected_before_reducer() -> None:
    from busybar_codex.events import SafeEvent

    with pytest.raises(ValueError):
        SafeEvent.from_json(
            json.dumps(
                {
                    "session_id": "a",
                    "state": "coding",
                    "timestamp": "2026-09-11T00:00:00",
                    "reason": "prompt",
                }
            )
        )


def test_claude_ask_user_question_is_a_question() -> None:
    event = normalize_hook(
        {"hook_event_name": "PreToolUse", "session_id": "a", "tool_name": "AskUserQuestion"}, NOW
    )
    assert event is not None
    assert event.state is DisplayState.QUESTION


@pytest.mark.parametrize("tool_name", [[], {}, None, True, 123, "", "x" * 129, "bad name"])
def test_malformed_tool_name_is_ignored(tool_name: object) -> None:
    assert (
        normalize_hook(
            {"hook_event_name": "PreToolUse", "session_id": "a", "tool_name": tool_name}, NOW
        )
        is None
    )


def test_claude_permission_notification_sets_question_without_message_text() -> None:
    event = normalize_hook(
        {
            "session_id": "a",
            "hook_event_name": "Notification",
            "notification_type": "permission_prompt",
            "message": "PRIVATE",
        },
        NOW,
    )
    assert event is not None
    assert event.state is DisplayState.QUESTION
    assert "PRIVATE" not in event.to_json()


@pytest.mark.parametrize("session", ["x" * 129, "bad\ud800", "private session name"])
def test_invalid_session_identifier_is_not_persisted(session: str) -> None:
    assert (
        normalize_hook({"hook_event_name": "UserPromptSubmit", "session_id": session}, NOW) is None
    )


@pytest.mark.parametrize("turn", ["", "x" * 129, "private turn text", "bad\ud800", [], 123])
def test_invalid_turn_identifier_is_not_persisted(turn: object) -> None:
    assert (
        normalize_hook(
            {"hook_event_name": "UserPromptSubmit", "session_id": "s1", "turn_id": turn}, NOW
        )
        is None
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("turn_id", "private turn text"),
        ("turn_id", "x" * 129),
        ("turn_id", ""),
        ("reason", "private reason text"),
        ("reason", "x" * 129),
        ("reason", "unknown_reason"),
    ],
)
def test_persisted_event_rejects_unnormalized_fields(field: str, value: str) -> None:
    from busybar_codex.events import SafeEvent

    raw = {
        "session_id": "s1",
        "turn_id": "t1",
        "state": "coding",
        "timestamp": NOW.isoformat(),
        "reason": "prompt",
    }
    raw[field] = value
    with pytest.raises(ValueError):
        SafeEvent.from_json(json.dumps(raw))


@pytest.mark.parametrize("tool_name", ["exec_command", "Bash", "mcp__server__tool"])
def test_ordinary_tool_start_records_activity_without_private_fields(tool_name: str) -> None:
    from busybar_codex.events import SafeEvent

    event = normalize_hook(
        {
            "hook_event_name": "PreToolUse",
            "session_id": "s1",
            "tool_name": tool_name,
            "tool_input": {"command": "PRIVATE"},
        },
        NOW,
    )
    assert event is not None
    assert event.state is DisplayState.CODING
    assert event.reason == "tool_started"
    assert tool_name not in event.to_json()
    assert "PRIVATE" not in event.to_json()
    assert SafeEvent.from_json(event.to_json()) == event


@pytest.mark.parametrize("tool_name", ["request_user_input", "AskUserQuestion"])
def test_explicit_question_completion_has_separate_safe_reason(tool_name: str) -> None:
    from busybar_codex.events import SafeEvent

    event = normalize_hook(
        {"hook_event_name": "PostToolUse", "session_id": "s1", "tool_name": tool_name}, NOW
    )
    assert event is not None
    assert event.state is DisplayState.CODING
    assert event.reason == "user_input_complete"
    assert SafeEvent.from_json(event.to_json()) == event


@pytest.mark.parametrize(
    ("hook", "reason"),
    [("PreCompact", "compact_started"), ("PostCompact", "compact_complete")],
)
def test_compaction_records_safe_activity(hook: str, reason: str) -> None:
    from busybar_codex.events import SafeEvent

    event = normalize_hook(
        {"hook_event_name": hook, "session_id": "s1", "compact_summary": "PRIVATE"}, NOW
    )
    assert event is not None
    assert event.state is DisplayState.CODING
    assert event.reason == reason
    assert "PRIVATE" not in event.to_json()
    assert SafeEvent.from_json(event.to_json()) == event


@pytest.mark.parametrize(
    "message",
    [
        "Want me to also add X?",
        "Would you like me to add optional tests?",
        "Does that make sense?",
        "Хочешь, я также добавлю X?",
        "Готово. Всё понятно?",
        "The example asks: which option?",
    ],
)
def test_optional_offer_or_generic_question_does_not_claim_human_wait(message: str) -> None:
    event = normalize_hook(
        {"session_id": "s1", "hook_event_name": "Stop", "last_assistant_message": message}, NOW
    )
    assert event is not None
    assert event.state is DisplayState.DONE
    assert event.reason == "stop"


def test_idle_notification_after_stop_does_not_reopen_session() -> None:
    from busybar_codex.state import SessionReducer

    reducer = SessionReducer(86400)
    stopped = normalize_hook({"session_id": "s1", "hook_event_name": "Stop"}, NOW)
    assert stopped is not None
    reducer.apply(stopped)
    idle = normalize_hook(
        {"session_id": "s1", "hook_event_name": "Notification", "notification_type": "idle_prompt"},
        NOW,
    )
    assert idle is None
    assert reducer.records["s1"].state is DisplayState.DONE
