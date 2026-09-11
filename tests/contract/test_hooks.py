from datetime import UTC, datetime

from busybar_codex.events import DisplayState, normalize_hook


def test_codex_request_user_input_shape_is_reduced_without_arguments() -> None:
    private_question = "Should production be overwritten?"
    payload = {
        "session_id": "thr_123",
        "transcript_path": "D:/private/rollout.jsonl",
        "cwd": "D:/private/project",
        "permission_mode": "default",
        "hook_event_name": "PreToolUse",
        "tool_name": "request_user_input",
        "tool_input": {"questions": [{"question": private_question}]},
    }

    event = normalize_hook(payload, datetime(2026, 9, 11, tzinfo=UTC))

    assert event is not None
    assert event.session_id == "thr_123"
    assert event.state is DisplayState.QUESTION
    assert private_question not in event.to_json()
    assert "rollout.jsonl" not in event.to_json()
